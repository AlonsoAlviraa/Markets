
import asyncio
import logging
from typing import Dict, List, Optional
from src.core.feed import MarketDataFeed
from src.core.orderbook import OrderBook
from src.exchanges.polymarket_clob import PolymarketOrderExecutor

class SimpleMarketMaker:
    """
    Simple Market Making Strategy.
    - Subscribes to Token IDs.
    - Maintains local BBO/Book.
    - Calculates Quotes around Mid-Price.
    - Executes LIMIT orders (if dry_run=False).
    """
    
    def __init__(self, token_ids: List[str], executor: Optional[PolymarketOrderExecutor] = None, dry_run: bool = True, spread: float = 0.02, size: float = 10.0):
        self.token_ids = token_ids
        self.executor = executor
        self.dry_run = dry_run
        self.spread = spread # 2 cents spread
        self.size = size
        self.books: Dict[str, OrderBook] = {tid: OrderBook(tid) for tid in token_ids}
        self.feed = MarketDataFeed()
        self.feed.add_callback(self.on_market_update)
        
        # Track our open orders: TokenID -> {'BID': order_id, 'ASK': order_id}
        self.active_orders: Dict[str, Dict[str, str]] = {tid: {} for tid in token_ids}
        
    async def start(self):
        print(f"[START] Starting Market Maker for {len(self.token_ids)} tokens... (Dry Run: {self.dry_run})")
        
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
        # elif event_type == "book":
        #      print("[DEBUG] Book Snapshot received")
        # else:
        #      print(f"[DEBUG] Other event: {event_type}")
            
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
            asyncio.create_task(self.update_quotes(token_id, mid, book))
            
    async def update_quotes(self, token_id, mid, book):
        # Desired Bid/Ask
        # TODO: Skew based on Inventory here
        my_bid = round(mid - (self.spread / 2), 3)
        my_ask = round(mid + (self.spread / 2), 3)
        
        # Safety checks
        if my_bid <= 0 or my_ask >= 1.0 or my_bid >= my_ask: return

        bb, _ = book.get_best_bid()
        ba, _ = book.get_best_ask()
        
        log_msg = f"[QUOTE] {token_id[:10]}... | Mid: {mid:.3f} | Market: {bb:.3f}-{ba:.3f} | Mine: {my_bid:.3f}-{my_ask:.3f}"
        
        if self.dry_run:
            print(log_msg + " (DRY)")
        else:
            print(log_msg + " (LIVE)")
            await self.execute_quotes(token_id, my_bid, my_ask)

    async def execute_quotes(self, token_id, bid_price, ask_price):
        """
        Cancel previous orders and place new ones.
        This is a naive implementation (Cancel-All-Replace).
        Pro version would diff/amend.
        """
        if not self.executor: return
        
        # Cancel previous
        orders = self.active_orders.get(token_id, {})
        if orders.get('BID'):
             self.executor.cancel_order(orders['BID'])
        if orders.get('ASK'):
             self.executor.cancel_order(orders['ASK'])
             
        # Place new
        # We run these concurrently to be faster
        # In python synchronous executor, we might block event loop. 
        # Ideally place_order should be async. The current PolymarketOrderExecutor is sync blocking IO logic inside async loop.
        # We should use run_in_executor to avoid blocking the WS loop.
        
        loop = asyncio.get_running_loop()
        
        # Place Bid
        bid_oid = await loop.run_in_executor(None, self.executor.place_order, token_id, 'BUY', bid_price, self.size)
        
        # Place Ask
        ask_oid = await loop.run_in_executor(None, self.executor.place_order, token_id, 'SELL', ask_price, self.size)
        
        self.active_orders[token_id] = {'BID': bid_oid, 'ASK': ask_oid}

if __name__ == "__main__":
    # Test with a dummy ID (or fetch one if running standalone)
    pass

