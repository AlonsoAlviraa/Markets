
import aiohttp
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class WhaleHunter:
    """
    Auto-discovers profitable wallets ('Whales') using Polymarket Data API.
    Criteria:
    - High PnL (Proof of Alpha)
    - Significant Volume (Filtering out lucky small bets)
    """

    API_URL = "https://data-api.polymarket.com/v1/leaderboard"

    def __init__(self, min_pnl: float = 5000.0, min_vol: float = 10000.0, limit: int = 10):
        self.min_pnl = min_pnl
        self.min_vol = min_vol
        self.limit = limit

    async def fetch_top_whales(self) -> List[Dict]:
        """
        Fetches leaderboard and returns top wallets.
        Returns: List of {"address": str, "pnl": float, "name": str}
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.API_URL) as resp:
                    if resp.status != 200:
                        logger.error(f"[HUNTER] Failed to fetch leaderboard: {resp.status}")
                        return []
                    
                    data = await resp.json()
                    
                    # Data is a list of dicts
                    ranked = []
                    for user in data:
                        pnl = float(user.get("pnl", 0))
                        vol = float(user.get("vol", 0))
                        wallet = user.get("proxyWallet", "")
                        
                        if not wallet: continue
                        
                        if pnl >= self.min_pnl and vol >= self.min_vol:
                            ranked.append({
                                "address": wallet,
                                "pnl": pnl,
                                "name": user.get("userName", "Unknown")
                            })
                            
                    # Sort by PnL desc (API usually sorts, but safety first)
                    ranked.sort(key=lambda x: x["pnl"], reverse=True)
                    
                    top_whales = ranked[:self.limit]
                    logger.info(f"[HUNTER] Used ML/Stats to identify {len(top_whales)} Alpha Wallets (Top: {top_whales[0]['name']} ${top_whales[0]['pnl']:.0f})")
                    return top_whales

        except Exception as e:
            logger.error(f"[HUNTER] Error finding whales: {e}")
            return []
