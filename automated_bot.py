import asyncio
import os
import sys
from typing import Dict
from datetime import datetime
from src.core.arbitrage_detector import ArbitrageDetector
from src.strategies.atomic_arbitrage import AtomicArbitrageScanner
from src.utils.telegram_bot import TelegramBot
from dotenv import load_dotenv

load_dotenv()

class AutomatedArbitrageBot:
    """
    Signal-Only Arbitrage Bot.
    Scans for opportunities and sends Telegram alerts.
    """
    
    def __init__(self):
        # Load configuration
        self.min_profit = float(os.getenv("MIN_PROFIT_PERCENT", "3.0"))
        self.max_position_size = float(os.getenv("MAX_POSITION_SIZE", "10.0"))
        self.scan_interval = int(os.getenv("SCAN_INTERVAL", "60"))
        
        # Initialize components
        self.detector = ArbitrageDetector(min_profit_percent=self.min_profit)
        self.atomic_scanner = AtomicArbitrageScanner()
        # Override atomic settings with env vars if needed
        self.atomic_scanner.MIN_PROFIT_THRESHOLD = self.min_profit / 100
        
        # Initialize Telegram
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.telegram = None
        if telegram_token and telegram_chat_id:
            self.telegram = TelegramBot(telegram_token, telegram_chat_id)
        
        # Stats
        self.total_signals = 0
        self.start_time = datetime.now()
        
        self.mode = "SIGNAL_ONLY"
        print(f"🤖 Automated Arbitrage Bot initialized ({self.mode})")
        print(f"   Min profit: {self.min_profit}%")
        print(f"   Scan interval: {self.scan_interval}s")
        if self.telegram:
            print("   Telegram: Active")
        else:
            print("   Telegram: Disabled (Check .env)")

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
    
    async def run_scan_cycle(self):
        """Run one scan cycle"""
        try:
            # 1. Scan for Atomic Arbitrage (High Priority)
            print("\n🔍 Scanning for Atomic Arbitrage...")
            atomic_opps = await self.atomic_scanner.scan_for_opportunities()
            
            if atomic_opps:
                print(f"✨ Found {len(atomic_opps)} atomic opportunities!")
                for opp in atomic_opps:
                    self.total_signals += 1
                    if self.telegram:
                        await self.telegram.send_atomic_alert(opp, self.max_position_size)
            
            # 2. Scan for Inter-Exchange Arbitrage
            print("\n🔍 Scanning for Inter-Exchange Arbitrage...")
            opportunities = await self.detector.scan_for_opportunities()
            
            # Notify for all opportunities
            for opp in opportunities:
                await self.notify_opportunity(opp)
            
            if not opportunities and not atomic_opps:
                print("   No opportunities found this cycle.")
        
        except Exception as e:
            print(f"❌ Scan cycle error: {e}")
            if self.telegram:
                await self.telegram.send_message(f"⚠️ Scan error: {str(e)[:200]}")
    
    async def run(self):
        """Main bot loop - runs continuously"""
        print(f"\n🚀 Bot starting... Scanning every {self.scan_interval}s")
        
        if self.telegram:
            await self.telegram.send_message(
                f"🤖 Arbitrage Signal Bot Started\n"
                f"Min profit: {self.min_profit}%\n"
                f"Bet Sizing: ${self.max_position_size}"
            )
        
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
