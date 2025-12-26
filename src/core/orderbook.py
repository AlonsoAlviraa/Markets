
from typing import Dict, Optional, Tuple
from decimal import Decimal

class OrderBook:
    """
    Maintains a local L2 Order Book state.
    """
    def __init__(self, market_id: str):
        self.market_id = market_id
        # Price -> Size (Float or Decimal)
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.last_update_id = 0
        
    def update(self, side: str, price: float, size: float):
        """
        Update a level in the book.
        side: 'BUY' (Bid) or 'SELL' (Ask)
        price: Price level
        size: New size (0 to remove level)
        """
        book = self.bids if side.upper() == "BUY" else self.asks
        
        if size <= 0:
            if price in book:
                del book[price]
        else:
            book[price] = size
            
    def get_best_bid(self) -> Tuple[Optional[float], float]:
        """Return (price, size) of best bid"""
        if not self.bids: return None, 0.0
        best_price = max(self.bids.keys())
        return best_price, self.bids[best_price]

    def get_best_ask(self) -> Tuple[Optional[float], float]:
        """Return (price, size) of best ask"""
        if not self.asks: return None, 0.0
        best_price = min(self.asks.keys())
        return best_price, self.asks[best_price]

    def get_mid_price(self) -> Optional[float]:
        bb, _ = self.get_best_bid()
        ba, _ = self.get_best_ask()
        if bb is not None and ba is not None:
             return (bb + ba) / 2
        return None
        
    def get_spread(self) -> Optional[float]:
        bb, _ = self.get_best_bid()
        ba, _ = self.get_best_ask()
        if bb is not None and ba is not None:
             return ba - bb
        return None

    def clear(self):
        self.bids.clear()
        self.asks.clear()
