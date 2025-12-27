
import logging
import time
from datetime import datetime

logger = logging.getLogger("MegaDebug")

class MegaDebugger:
    """
    Centralized Visualization for the 'Bot Cerebro'.
    Prints clearly formatted blocks for:
    - 📊 MARKET COMPARISONS (Arbitrage)
    - 🐋 WHALE TRACKING (Spy Network)
    - 📢 ALERTS (Telegram)
    """

    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"

    @staticmethod
    def log_market_check(market_title: str, spread: float, profit: float, source: str = "Poly"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = MegaDebugger.OKGREEN if profit > 0 else MegaDebugger.OKBLUE
        print(f"{MegaDebugger.BOLD}[{timestamp}] 📊 MARKET CHECK{MegaDebugger.ENDC}")
        print(f"   Market: {market_title[:50]}...")
        print(f"   Spread: {spread:.2f}% | {color}Est. Profit: {profit:.2f}%{MegaDebugger.ENDC} | Src: {source}")
        print("-" * 40)

    @staticmethod
    def log_whale_activity(wallet: str, action: str, token: str, amount: float, whale_name: str = "Unknown"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        action_icon = "🟢" if action == "BUY" else "🔴"
        print(f"\n{MegaDebugger.BOLD}{MegaDebugger.OKCYAN}[{timestamp}] 🐋 WHALE DETECTED ({whale_name}){MegaDebugger.ENDC}")
        print(f"   {action_icon} Action: {action} {amount:.2f} shares")
        print(f"   🎫 Token:  {token}")
        print(f"   💼 Wallet: {wallet[:8]}...")
        print("=" * 40 + "\n")

    @staticmethod
    def log_alert_sent(platform: str, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"{MegaDebugger.BOLD}{MegaDebugger.WARNING}[{timestamp}] 📢 ALERT SENT ({platform}){MegaDebugger.ENDC}")
        print(f"   Msg: {message.splitlines()[0]}...") # Print first line only
        print("-" * 40)
    
    @staticmethod
    def log_status(status: str):
         print(f"{MegaDebugger.BOLD}>> SYSTEM STATUS: {status}{MegaDebugger.ENDC}")

