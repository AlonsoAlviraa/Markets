
import asyncio
import logging
from typing import List, Dict, Optional
from src.exchanges.polymarket_clob import PolymarketOrderExecutor
from src.strategies.spy_network import PolygonSpy
from src.strategies.whale_hunter import WhaleHunter
from src.utils.notifier import send_telegram_alert

logger = logging.getLogger(__name__)

class CopyBot:
    """
    KOPY KAT v1: Follows 'Whale' wallets via direct On-Chain/PolygonScan polling.
    Includes Auto-Discovery Mode (WhaleHunter).
    """

    def __init__(self, target_wallets: List[str], executor: PolymarketOrderExecutor, scale_factor: float = 0.1, max_bet: float = 50.0):
        self.target_wallets = target_wallets
        self.executor = executor
        self.scale_factor = scale_factor
        self.max_bet = max_bet
        self.active = False
        
        # Auto-Discovery
        self.hunter = WhaleHunter(limit=10) # Auto-find top 10 whales
        
        # Initialize Spy
        self.spy = PolygonSpy(self.target_wallets, self.on_trade_event)
    
    async def start(self):
        self.active = True
        logger.info(f"[COPY] Started CopyBot observing {len(self.target_wallets)} whales.")
        
        # Initial Whale Hunt
        await self.refresh_targets()
        
        # Start Spy
        asyncio.create_task(self.spy.start())
        
        # Periodic Refresh Task
        asyncio.create_task(self.auto_refresh_loop())
        
    async def refresh_targets(self):
        """Fetch top whales and update Spy targets."""
        try:
            new_whales = await self.hunter.fetch_top_whales()
            if new_whales:
                # Merge with config whales
                for w in new_whales:
                    addr = w['address']
                    if addr.lower() not in [t.lower() for t in self.target_wallets]:
                        self.target_wallets.append(addr)
                        # Log to MegaDebugger
                        from src.utils.mega_debugger import MegaDebugger
                        print(f"{MegaDebugger.OKGREEN}[COPY] ➕ Added new Alpha Wallet: {addr[:6]}... ({w['name']}){MegaDebugger.ENDC}")
                        logger.info(f"[COPY] Added {addr}")
                
                # Update Spy
                self.spy.targets = [t.lower() for t in self.target_wallets]
                logger.info(f"[COPY] Spy Network now tracking {len(self.spy.targets)} targets.")
        except Exception as e:
            logger.error(f"[COPY] Failed to refresh targets: {e}")

    async def auto_refresh_loop(self):
        while self.active:
            await asyncio.sleep(3600 * 4) # Every 4 hours
            await self.refresh_targets()

    async def stop(self):
        self.active = False
        await self.spy.stop()
        
    async def on_trade_event(self, trade: Dict):
        """
        Called when Spy detects a trade.
        trade = {wallet, type, side, token_id, amount, tx_hash}
        """
        if not self.active: return
        
        wallet = trade['wallet']
        side = trade['side'] # BUY/SELL
        token_id = trade['token_id']
        amount = trade['amount']
        
        # Log and Alert
        # logger.info(f"[COPY] 🎯 MATCH: {wallet[:6]} {side} {token_id} (Amt: {amount})")

        # Mega Debugger Hook
        from src.utils.mega_debugger import MegaDebugger
        MegaDebugger.log_whale_activity(wallet, side, token_id, amount)
        
        msg = (
            f"🐋 **WHALE ALERT**\n"
            f"Target: `{wallet[:6]}...`\n"
            f"Action: **{side}**\n"
            f"Asset: `{token_id}`\n"
            f"Size: {amount:.2f} shares\n"
            f"🔗 [View TX](https://polygonscan.com/tx/{trade['tx_hash']})"
        )
        send_telegram_alert(msg)
        MegaDebugger.log_alert_sent("TELEGRAM", msg)
