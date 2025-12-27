
import asyncio
import os
import sys
import aiohttp
import json
from typing import Dict
from datetime import datetime
from src.core.arbitrage_detector import ArbitrageDetector
from src.strategies.atomic_arbitrage import AtomicArbitrageScanner
from src.core.atomic_executor import AtomicExecutor
from src.exchanges.polymarket_clob import PolymarketOrderExecutor
from src.strategies.market_maker import SimpleMarketMaker
from src.wallet.wallet_manager import WalletManager
from src.utils.telegram_bot import TelegramBot
from dotenv import load_dotenv

load_dotenv()

class AutomatedArbitrageBot:
    """
    Arbitrage Bot with Signal, Execution, and Market Making capabilities.
    """
    
    def __init__(self):
        # Load configuration
        self.min_profit = float(os.getenv("MIN_PROFIT_PERCENT", "3.0"))
        self.max_position_size = float(os.getenv("MAX_POSITION_SIZE", "10.0"))
        self.scan_interval = int(os.getenv("SCAN_INTERVAL", "60"))
        
        # Execution flags
        self.enable_atomic_execution = os.getenv("ENABLE_ATOMIC_EXECUTION", "false").lower() == "true"
        self.enable_market_making = os.getenv("ENABLE_MARKET_MAKING", "false").lower() == "true"
        self.mm_dry_run = os.getenv("MARKET_MAKING_DRY_RUN", "true").lower() == "true"
        
        # Initialize components
        self.detector = ArbitrageDetector(min_profit_percent=self.min_profit)
        self.atomic_scanner = AtomicArbitrageScanner()
        self.atomic_scanner.MIN_PROFIT_THRESHOLD = self.min_profit / 100
        
        # Initialize Execution (Atomic + CLOB)
        self.executor = None
        self.clob_executor = None
        
        # Try to init CLOB Executor if needed
        if self.enable_atomic_execution or self.enable_market_making:
            try:
                # Check for CLOB keys existence first to avoid crash
                if os.getenv("PRIVATE_KEY") or os.getenv("POLY_KEY"):
                    self.clob_executor = PolymarketOrderExecutor()
                    print("✅ CLOB Executor initialized")
                else:
                    print("⚠️ CLOB Executor skipped (No Private Key found)")
            except Exception as e:
                 print(f"❌ CLOB Executor init failed: {e}")

        if self.enable_atomic_execution:
            try:
                self.wallet_manager = WalletManager()
                self.executor = AtomicExecutor(self.wallet_manager)
                print("✅ Atomic Execution ENABLED (CTF + CLOB)")
            except Exception as e:
                print(f"❌ Atomic Execution init failed: {e}")
                self.enable_atomic_execution = False
        
        # Initialize Market Maker (if enabled)
        self.market_maker = None
        if self.enable_market_making:
            status = "DRY RUN" if self.mm_dry_run else "LIVE TRADING"
            print(f"🔷 Market Making ENABLED ({status}) (Startup deferred)")
        
        # Initialize Telegram
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.telegram = None
        if telegram_token and telegram_chat_id:
            self.telegram = TelegramBot(telegram_token, telegram_chat_id)
        
        # Stats
        self.total_signals = 0
        self.start_time = datetime.now()
        
        modes = []
        if self.enable_atomic_execution: modes.append("EXECUTION")
        if self.enable_market_making: 
             modes.append("MARKET_MAKING")
             if not self.clob_executor and not self.mm_dry_run:
                  print("⚠️ MM is LIVE but no Executor! Switching to DRY RUN forced.")
                  self.mm_dry_run = True
                  
        if not modes: modes.append("SIGNAL_ONLY")
        
        self.mode = "+".join(modes)
        print(f"🤖 Automated Arbitrage Bot initialized ({self.mode})")
        print(f"   Min profit: {self.min_profit}%")
        print(f"   Scan interval: {self.scan_interval}s")
        if self.telegram:
            print("   Telegram: Active")
        else:
            print("   Telegram: Disabled (Check .env)")

    # ... (Keep existing methods) ...
    # notify_opportunity, execute_atomic_opportunity, get_active_token_id, run_scan_cycle

    async def notify_opportunity(self, opportunity: Dict) -> bool:
        """
        Notify about arbitrage opportunity (Signal Only).
        """
        try:
            print(f"\n🔔 SIGNAL DETECTED!")
            print(f"   Event: {opportunity['poly_event']['title'][:60]}")
            print(f"   Profit: {opportunity['profit_percent']:.2f}%")
            
            # Send Telegram notification
            if self.telegram:
                await self.telegram.send_arb_alert(opportunity, self.max_position_size)
            
            self.total_signals += 1
            return True
            
        except Exception as e:
            print(f"   ❌ Signal failed: {e}")
            return False
            
    async def execute_atomic_opportunity(self, opp):
        """Execute atomic mint/merge transaction"""
        if not self.executor or not self.clob_executor: return
        
        tx_hash = None
        
        # Strategy: SPLIT & SELL (Arb > 1.0)
        if opp.direction == "SPLIT_SELL":
            print(f"⚡ Executing SPLIT_SELL on {opp.market_title[:30]}...")
            
            # 1. Execute Split (On-Chain)
            tx_hash = await self.executor.execute_split(opp.condition_id, self.max_position_size)
            
            if tx_hash:
                if self.telegram:
                     await self.telegram.send_message(f"✅ One-Chain Split Confirmed: {tx_hash}\nSelling tokens...")
                
                # 2. Sell Tokens (CLOB)
                shares = self.max_position_size
                
                print(f"   Selling {shares} YES @ {opp.yes_price}...")
                order_yes = self.clob_executor.place_order(
                    token_id=opp.yes_token_id,
                    side="SELL",
                    price=opp.yes_price,
                    size=shares
                )
                
                print(f"   Selling {shares} NO @ {opp.no_price}...")
                order_no = self.clob_executor.place_order(
                    token_id=opp.no_token_id,
                    side="SELL",
                    price=opp.no_price,
                    size=shares
                )
                
                if order_yes and order_no:
                    msg = f"💰 PROFIT SECURED!\nSold YES: {order_yes}\nSold NO: {order_no}"
                    print(msg)
                    if self.telegram: await self.telegram.send_message(msg)
                else:
                    err = f"⚠️ Sell Orders Incomplete. YES:{order_yes} NO:{order_no}. Check manual."
                    print(err)
                    if self.telegram: await self.telegram.send_message(err)

        elif opp.direction == "BUY_MERGE":
             print(f"⚡ Executing BUY_MERGE on {opp.market_title[:30]}...")
             shares = self.max_position_size
             
             # 1. Buy YES
             print(f"   Buying {shares} YES @ {opp.yes_price}...")
             oid_yes = self.clob_executor.place_order(opp.yes_token_id, "BUY", opp.yes_price, shares)
             
             # 2. Buy NO
             print(f"   Buying {shares} NO @ {opp.no_price}...")
             oid_no = self.clob_executor.place_order(opp.no_token_id, "BUY", opp.no_price, shares)
             
             if oid_yes and oid_no:
                 print("   ✅ Buy Orders Placed. Waiting for fills (5s)...")
                 await asyncio.sleep(5) # Wait for settlement/fills
                 
                 # 3. Merge (Redeem)
                 # Ideally we check balances first. For now, try merging.
                 tx_hash = await self.executor.execute_merge(opp.condition_id, shares)
                 
                 if tx_hash:
                     msg = f"💰 CYCLE COMPLETE: Bought & Merged! TX: {tx_hash}"
                     print(msg)
                     if self.telegram: await self.telegram.send_message(msg)
                 else:
                     print("❌ Merge Failed (Check balances)")
             else:
                 print("⚠️ Buy Orders Failed")
    
    async def get_active_token_id(self):
        """Fetch one active token ID from Gamma API"""
        url = "https://gamma-api.polymarket.com/events?limit=1&closed=false&order=volume24hr&ascending=false"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    data = await resp.json()
                    if data and data[0].get('markets'):
                        market = data[0]['markets'][0]
                        raw_ids = market.get('clobTokenIds')
                        ids = json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
                        return ids[0] if ids else None
        except Exception as e:
            print(f"Failed to fetch MM token: {e}")
            return None
    
    async def run_scan_cycle(self):
        """Run one scan cycle"""
        try:
            # 1. Scanner Atómico
            print("\n🔍 Scanning for Atomic Arbitrage...")
            atomic_opps = await self.atomic_scanner.scan_for_opportunities()
            
            if atomic_opps:
                print(f"✨ Found {len(atomic_opps)} atomic opportunities!")
                for opp in atomic_opps:
                    self.total_signals += 1
                    if self.telegram:
                        await self.telegram.send_atomic_alert(opp, self.max_position_size)
                    if self.enable_atomic_execution:
                        await self.execute_atomic_opportunity(opp)
            
            # 2. Scanner Inter-Exchange
            print("\n🔍 Scanning for Inter-Exchange Arbitrage...")
            opportunities = await self.detector.scan_for_opportunities()
            
            # MEGA DEBUGGER HOOK
            from src.utils.mega_debugger import MegaDebugger
            for opp in opportunities:
                # Log to Mega Debugger
                MegaDebugger.log_market_check(
                    market_title=opp['poly_event']['title'],
                    spread=0.0, # N/A for Detector currently
                    profit=opp['profit_percent'],
                    source="Polymarket+SX"
                )
                await self.notify_opportunity(opp)
            
            if not opportunities and not atomic_opps:
                 MegaDebugger.log_status(f"Scan Complete. Clean Cycle.")
                 print("   No opportunities found this cycle.")
        
        except Exception as e:
            print(f"❌ Scan cycle error: {e}")
            if self.telegram:
                await self.telegram.send_message(f"⚠️ Scan error: {str(e)[:200]}")

    async def run(self):
        """Main bot loop - runs continuously"""
        print(f"\n🚀 Bot starting... Scanning every {self.scan_interval}s")
        
        if self.telegram:
            try:
                await self.telegram.send_message(
                    f"🤖 *Arbitrage Bot Started ({self.mode})*\n"
                    f"🎯 Min profit: {self.min_profit}%\n"
                    f"💰 Bet Size: ${self.max_position_size}\n"
                    f"⚡ Modes: {self.mode}\n"
                )
                print("   ✅ Telegram startup message sent")
            except Exception as e:
                print(f"   ❌ Failed to send Telegram startup message: {e}")
        
        # Start Market Maker Task if enabled
        mm_task = None
        if self.enable_market_making:
            token_id = await self.get_active_token_id()
            if token_id:
                print(f"🔷 Starting MM for token {token_id}...")
                self.market_maker = SimpleMarketMaker(
                    token_ids=[str(token_id)],
                    executor=self.clob_executor,
                    dry_run=self.mm_dry_run
                )
                mm_task = asyncio.create_task(self.market_maker.start())
            else:
                print("❌ Could not find token for Market Making.")

        # Initialize Copy Bot (Phase 6)
        self.copy_bot = None
        if self.clob_executor: 
            # Import here to avoid circular deps if any
            from src.strategies.copy_bot import CopyBot
            from config import WHALE_WALLETS
            
            # Start CopyBot even if WHALE_WALLETS is empty (Auto-Discovery)
            print(f"🐋 Starting CopyBot (Spy Network)...")
            if WHALE_WALLETS:
                print(f"   Tracking {len(WHALE_WALLETS)} static whales from config.")
            else:
                print(f"   No static whales. Relying on Auto-Discovery (WhaleHunter).")

            self.copy_bot = CopyBot(WHALE_WALLETS, self.clob_executor)
            asyncio.create_task(self.copy_bot.start())



        try:
            while True:
                await self.run_scan_cycle()
                await asyncio.sleep(self.scan_interval)
                
        except KeyboardInterrupt:
            print("\n🛑 Bot stopped by user")
        except Exception as e:
            print(f"\n💥 Fatal error: {e}")
            if self.telegram:
                await self.telegram.send_message(f"🚨 BOT CRASHED: {str(e)[:200]}")
        finally:
            if self.market_maker and hasattr(self.market_maker, 'feed'):
               await self.market_maker.feed.stop()
            if hasattr(self.detector, 'close'):
                await self.detector.close()
            
            if self.telegram:
                uptime = (datetime.now() - self.start_time).total_seconds() / 3600
                await self.telegram.send_message(
                    f"Bot stopped\nUptime: {uptime:.1f}h\nSignals Found: {self.total_signals}"
                )


if __name__ == "__main__":
    bot = AutomatedArbitrageBot()
    asyncio.run(bot.run())
