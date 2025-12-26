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
        
        # Initialize components
        self.detector = ArbitrageDetector(min_profit_percent=self.min_profit)
        self.atomic_scanner = AtomicArbitrageScanner()
        self.atomic_scanner.MIN_PROFIT_THRESHOLD = self.min_profit / 100
        
        # Initialize Execution (if enabled)
        self.executor = None
        self.clob_executor = None
        if self.enable_atomic_execution:
            try:
                self.wallet_manager = WalletManager()
                self.executor = AtomicExecutor(self.wallet_manager)
                self.clob_executor = PolymarketOrderExecutor()
                print("✅ Atomic Execution ENABLED (CTF + CLOB)")
            except Exception as e:
                print(f"❌ Failed to init execution: {e}")
                self.enable_atomic_execution = False
        
        # Initialize Market Maker (if enabled)
        self.market_maker = None
        if self.enable_market_making:
            print("🔷 Market Making ENABLED (Startup deferred)")
        
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
        if self.enable_market_making: modes.append("MARKET_MAKING")
        if not modes: modes.append("SIGNAL_ONLY")
        
        self.mode = "+".join(modes)
        print(f"🤖 Automated Arbitrage Bot initialized ({self.mode})")
        print(f"   Min profit: {self.min_profit}%")
        print(f"   Scan interval: {self.scan_interval}s")
        if self.telegram:
            print("   Telegram: Active")
        else:
            print("   Telegram: Disabled (Check .env)")

    # ... notify_opportunity ... (Same as before)
    # ... execute_atomic_opportunity ... (Same as before)
    
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
    
    # ... run_scan_cycle ... (Same as before)

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
                self.market_maker = SimpleMarketMaker(token_ids=[str(token_id)])
                # Run MM start in background
                mm_task = asyncio.create_task(self.market_maker.start())
            else:
                print("❌ Could not find token for Market Making.")

        try:
            while True:
                # Run scan cycle
                await self.run_scan_cycle()
                
                # Sleep interval
                await asyncio.sleep(self.scan_interval)
                
        except KeyboardInterrupt:
            print("\n🛑 Bot stopped by user")
        except Exception as e:
            print(f"\n💥 Fatal error: {e}")
            if self.telegram:
                await self.telegram.send_message(f"🚨 BOT CRASHED: {str(e)[:200]}")
        finally:
            # Stop MM
            if self.market_maker and hasattr(self.market_maker, 'feed'):
               await self.market_maker.feed.stop()
            
            # Close resources
            if hasattr(self.detector, 'close'):
                await self.detector.close()
            
            # Send final stats
            uptime = (datetime.now() - self.start_time).total_seconds() / 3600
            if self.telegram:
                await self.telegram.send_message(
                    f"Bot stopped\n"
                    f"Uptime: {uptime:.1f}h\n"
                    f"Signals Found: {self.total_signals}"
                )

if __name__ == "__main__":
    bot = AutomatedArbitrageBot()
    asyncio.run(bot.run())
