
import asyncio
from typing import Dict, Tuple
from src.wallet.wallet_manager import WalletManager

class InventoryManager:
    """
    Tracks inventory (Token Balances) for Market Making.
    - Periodically syncs with Chain/API.
    - Tracks local updates from Fills (Optimization).
    """
    
    def __init__(self, wallet_manager: WalletManager, update_interval: int = 30):
        self.wallet_manager = wallet_manager
        self.update_interval = update_interval
        self.balances: Dict[str, float] = {} # TokenID -> Amount
        self.usdc_balance = 0.0
        self.lock = asyncio.Lock()
        
    async def start(self):
        """Start periodic sync loop"""
        while True:
            try:
                await self.sync_balances()
            except Exception as e:
                print(f"[INV] Sync error: {e}")
            await asyncio.sleep(self.update_interval)

    async def sync_balances(self):
        """Fetch real balances from Chain/API"""
        # For now, simplistic: Get USDC.
        # Getting ALL token balances is hard via RPC without list.
        # We rely on strategy to tell us WHICH tokens to check.
        
        # TODO: Implement batch fetch for tracked tokens.
        # self.usdc_balance = self.wallet_manager.get_usdc_balance() # This is sync/blocking?
        # wallet_manager needs async support or run_in_executor.
        pass

    def update_local(self, token_id: str, delta: float):
        """Update balance based on a fill (Optimistic)"""
        current = self.balances.get(token_id, 0.0)
        self.balances[token_id] = current + delta

    def get_balance(self, token_id: str) -> float:
        return self.balances.get(token_id, 0.0)

    def get_exposure(self, yes_token: str, no_token: str) -> float:
        """
        Calculate net exposure. 
        If YES=100, NO=0 -> Exposure +100 YES.
        If YES=100, NO=100 -> Exposure 0 (Mergeable).
        """
        y = self.get_balance(yes_token)
        n = self.get_balance(no_token)
        return y - n # Simplified. 
