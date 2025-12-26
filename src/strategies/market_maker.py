
import asyncio
import logging
from typing import Dict, List
from src.core.feed import MarketDataFeed
from src.core.orderbook import OrderBook

class SimpleMarketMaker:
    """
    Simple Market Making Strategy.
    - Subscribes to Token IDs.
    - Maintains local BBO/Book.
    - Calculates Quotes around Mid-Price.
    """
    
    def __init__(self, token_ids: List[str], spread: float = 0.02, size: float = 10.0):
        self.token_ids = token_ids
        self.spread = spread # 2 cents spread
        self.size = size
        self.books: Dict[str, OrderBook] = {tid: OrderBook(tid) for tid in token_ids}
        self.feed = MarketDataFeed()
        self.feed.add_callback(self.on_market_update)
        
    async def start(self):
        print(f"[START] Starting Market Maker for {len(self.token_ids)} tokens...")
        
        # Start Feed
        asyncio.create_task(self.feed.start())
        
        # Subscribe
        # Wait a bit for connection
        await asyncio.sleep(2) 
        self.feed.subscribe(self.token_ids)
        
        # Keep running
        while True:
            await asyncio.sleep(1)
            
    async def on_market_update(self, msg: Dict):
        """Process WS message"""
        # DEBUG: Print raw message type
        # print(f"[DEBUG] Msg received: {msg.get('event_type')} keys={list(msg.keys())}")
        
        event_type = msg.get("event_type")
        
        if event_type == "price_change":
            self.process_price_change(msg)
        elif event_type == "book":
             print("[DEBUG] Book Snapshot received")
        else:
             print(f"[DEBUG] Other event: {event_type}")
            
    def process_price_change(self, msg: Dict):
        token_id = msg.get("asset_id")
        # DEBUG
        # print(f"[DEBUG] Price update for {token_id} (Tracking {len(self.books)})")
        
        if token_id not in self.books: return
        
        price = float(msg.get("price", 0))
        size = float(msg.get("size", 0))
        side = msg.get("side", "").upper() # BUY or SELL
        
        # Update Book
        book = self.books[token_id]
        book.update(side, price, size)
        
        # Recalculate Quote
        mid = book.get_mid_price()
        if mid:
            self.print_quote(token_id, mid, book)
            
    def print_quote(self, token_id, mid, book):
        # Desired Bid/Ask
        my_bid = mid - (self.spread / 2)
        my_ask = mid + (self.spread / 2)
        
        bb, _ = book.get_best_bid()
        ba, _ = book.get_best_ask()
        
        print(f"[QUOTE] {token_id[:10]}... | Mid: {mid:.3f} | Market: {bb:.3f}-{ba:.3f} | Mine: {my_bid:.3f}-{my_ask:.3f}")

if __name__ == "__main__":
    # Test with a dummy ID (or fetch one if running standalone)
    pass
