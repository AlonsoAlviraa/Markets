
import logging
import aiohttp
from typing import List, Callable, Dict
import time
from config import POLYGONSCAN_API_KEY

logger = logging.getLogger(__name__)

class PolygonSpy:
    """
    Monitors PolygonScan for ERC1155 transfers involving target wallets.
    Identifies 'Buys' (Incoming Tokens) and 'Sells' (Outgoing Tokens).
    """

    BASE_URL = "https://api.polygonscan.com/api"
    
    def __init__(self, target_wallets: List[str], callback: Callable[[Dict], None], api_key: str = None):
        self.targets = [t.lower() for t in target_wallets]
        self.callback = callback
        self.api_key = api_key or POLYGONSCAN_API_KEY
        self.last_block = 0
        self.is_running = False

    async def start(self):
        self.is_running = True
        logger.info(f"[SPY] Started monitoring {len(self.targets)} whales via PolygonScan...")
        
        # Determine start block (latest)
        self.last_block = await self._get_latest_block()
        
        while self.is_running:
            await self._poll()
            await asyncio.sleep(6) # Free tier limit is roughly 5 requests/sec, but we poll nicely.

    async def stop(self):
        self.is_running = False

    async def _get_latest_block(self) -> int:
        async with aiohttp.ClientSession() as session:
            try:
                params = {
                    "module": "proxy",
                    "action": "eth_blockNumber",
                    "apikey": self.api_key
                }
                async with session.get(self.BASE_URL, params=params) as resp:
                    data = await resp.json()
                    return int(data["result"], 16)
            except Exception as e:
                logger.error(f"[SPY] Failed to get start block: {e}")
                return 99999999

    async def _poll(self):
        async with aiohttp.ClientSession() as session:
            # We must poll for EACH wallet? Or can we filter? 
            # API requires one address per call.
            # If valid API Key: 5 calls/sec. Without: 1 call/5sec.
            # We'll cycle through targets.
            
            for wallet in self.targets:
                try:
                    await self._check_wallet(session, wallet)
                    await asyncio.sleep(1) # Pace ourselves
                except Exception as e:
                    logger.error(f"[SPY] Error checking {wallet[:6]}: {e}")

    async def _check_wallet(self, session, wallet):
        params = {
            "module": "account",
            "action": "token1155tx", # Polymarket uses ERC1155
            "address": wallet,
            "startblock": self.last_block + 1,
            "sort": "asc",
            "apikey": self.api_key
        }
        
        async with session.get(self.BASE_URL, params=params) as resp:
            data = await resp.json()
            status = data.get("status")
            result = data.get("result")
            
            if status == "1" and isinstance(result, list):
                for tx in result:
                    self._process_tx(wallet, tx)
                    # Update local last_block pointer to avoid re-reading
                    bn = int(tx["blockNumber"])
                    if bn > self.last_block:
                        self.last_block = bn

    def _process_tx(self, wallet: str, tx: Dict):
        # Decode: Incoming = BUY, Outgoing = SELL
        token_id = tx.get("tokenID")
        token_name = tx.get("tokenName", "Unknown")
        amount = float(tx.get("tokenValue", 0)) # Usually just 'value' field in 1155? Check docs.
        # PolygonScan 1155 'tokenValue' is the amount.
        
        is_buy = tx["to"].lower() == wallet.lower()
        side = "BUY" if is_buy else "SELL"
        
        logger.info(f"[SPY] 🕵️ Detected {side} by {wallet[:6]}... | Token: {token_id} | Amt: {amount}")
        
        event = {
            "wallet": wallet,
            "type": "trade",
            "side": side,
            "token_id": token_id, 
            "amount": amount,
            "tx_hash": tx.get("hash")
        }
        
        # Fire callback
        asyncio.create_task(self.callback(event))

if __name__ == "__main__":
    # Test stub
    async def pr(e): print(e)
    spy = PolygonSpy(["0x.."], pr)
    # asyncio.run(spy.start())
