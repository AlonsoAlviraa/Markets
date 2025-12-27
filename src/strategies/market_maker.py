import asyncio
import logging
from typing import Dict, List, Optional, Tuple

import aiohttp

from src.core.feed import MarketDataFeed
from src.core.orderbook import OrderBook
from src.exchanges.polymarket_clob import PolymarketOrderExecutor

logger = logging.getLogger(__name__)


class SimpleMarketMaker:
    """
    Simple Market Making Strategy.
    - Subscribes to Token IDs.
    - Maintains local BBO/Book.
    - Calculates Quotes around Mid-Price.
    - Executes LIMIT orders (if dry_run=False).
    """

    def __init__(
        self,
        token_ids: List[str],
        executor: Optional[PolymarketOrderExecutor] = None,
        dry_run: bool = True,
        spread: float = 0.02,
        size: float = 10.0,
        inside_spread_ratio: float = 0.5,
        inventory_skew: float = 0.05,
        wide_spread_threshold: float = 0.04,
        opportunity_score_threshold: float = 0.6,
    ):
        self.token_ids = token_ids
        self.executor = executor
        self.dry_run = dry_run
        self.spread = spread  # 2 cents spread by default
        self.size = size
        self.inside_spread_ratio = inside_spread_ratio
        self.inventory_skew = inventory_skew
        self.wide_spread_threshold = wide_spread_threshold
        self.opportunity_score_threshold = opportunity_score_threshold
        self.books: Dict[str, OrderBook] = {tid: OrderBook(tid) for tid in token_ids}
        self.feed = MarketDataFeed()
        self.feed.add_callback(self.on_market_update)

        # Track our open orders: TokenID -> {'BID': order_id, 'ASK': order_id}
        self.active_orders: Dict[str, Dict[str, str]] = {tid: {} for tid in token_ids}
        self.last_mid: Dict[str, float] = {}

    async def start(self):
        logger.info(
            "[START] Starting Market Maker for %s tokens... (Dry Run: %s)",
            len(self.token_ids),
            self.dry_run,
        )

        await self.fetch_initial_book()

        asyncio.create_task(self.feed.start())

        await asyncio.sleep(2)
        self.feed.subscribe(self.token_ids)

        while True:
            await asyncio.sleep(10)
            # Periodic Opportunity Scan
            opps = self.find_opportunities()
            if opps:
                top = opps[:3]
                for op in top:
                    logger.info(
                        "[OPP] Token %s... | Score: %.2f | Mechanics: %s",
                        op['token_id'][:8],
                        op['score'],
                        ", ".join(op['mechanics'])
                    )

    async def fetch_initial_book(self):
        """Fetch REST snapshot to initialize books."""
        logger.info("[INIT] Fetching initial orderbooks...")
        async with aiohttp.ClientSession() as session:
            for tid in self.token_ids:
                try:
                    await self._fetch_and_load_book(session, tid)
                except Exception:
                    logger.exception("[ERR] Initial fetch failed for %s", tid)

    async def _fetch_and_load_book(self, session: aiohttp.ClientSession, token_id: str):
        url = f"https://clob.polymarket.com/book?token_id={token_id}"
        async with session.get(url) as resp:
            if resp.status != 200:
                logger.warning("[WARN] Snapshot request failed for %s (%s)", token_id, resp.status)
                return

            data = await resp.json()
            await self._apply_snapshot(token_id, data)

    async def on_market_update(self, msg: Dict):
        """Process WebSocket messages from the feed."""
        event_type = msg.get("event_type")
        token_id = msg.get("asset_id")

        logger.debug("[DEBUG] Msg received: %s id=%s", event_type, token_id)

        if event_type == "price_change":
            self.process_price_change(msg)
        elif event_type == "book":
            await self.process_book_snapshot(msg)
        else:
            logger.debug("[DEBUG] Other event: %s", event_type)

    async def process_book_snapshot(self, msg: Dict):
        token_id = msg.get("asset_id")
        if not token_id or token_id not in self.books:
            return

        await self._apply_snapshot(token_id, msg)

    async def _apply_snapshot(self, token_id: str, snapshot: Dict):
        book = self.books[token_id]
        book.clear()

        bids = snapshot.get("bids", [])
        asks = snapshot.get("asks", [])

        for bid in bids:
            book.update("BUY", float(bid["price"]), float(bid["size"]))
        for ask in asks:
            book.update("SELL", float(ask["price"]), float(ask["size"]))

        mid = book.get_mid_price()
        if mid:
            await self.update_quotes(token_id, mid, book)

    def process_price_change(self, msg: Dict):
        token_id = msg.get("asset_id")
        if not token_id or token_id not in self.books:
            return

        price = float(msg.get("price", 0))
        size = float(msg.get("size", 0))
        side = msg.get("side", "").upper()  # BUY or SELL

        if side not in {"BUY", "SELL"}:
            logger.debug("[DEBUG] Ignoring update with side=%s", side)
            return

        book = self.books[token_id]
        book.update(side, price, size)

        mid = book.get_mid_price()
        if mid:
            asyncio.create_task(self.update_quotes(token_id, mid, book))

    def compute_book_metrics(self, token_id: str, book: Optional[OrderBook] = None) -> Dict:
        book = book or self.books[token_id]
        bb, _ = book.get_best_bid()
        ba, _ = book.get_best_ask()
        mid = book.get_mid_price()
        spread = book.get_spread()

        bid_depth = sum(book.bids.values())
        ask_depth = sum(book.asks.values())
        total_depth = bid_depth + ask_depth
        imbalance = 0.0
        if total_depth > 0:
            imbalance = (bid_depth - ask_depth) / total_depth

        prev_mid = self.last_mid.get(token_id, mid or 0.0)
        mid_change = (mid or prev_mid) - prev_mid
        metrics = {
            "mid": mid,
            "spread": spread,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "imbalance": imbalance,
            "wide_spread": bool(spread is not None and spread >= self.wide_spread_threshold),
            "mid_change": mid_change,
        }

        if mid is not None:
            self.last_mid[token_id] = mid

        return metrics

    def _generate_quote_prices(
        self, token_id: str, mid: float, book: OrderBook, metrics: Optional[Dict] = None
    ) -> Optional[Tuple[float, float]]:
        metrics = metrics or self.compute_book_metrics(token_id, book)
        bb, _ = book.get_best_bid()
        ba, _ = book.get_best_ask()

        if bb is None or ba is None:
            return None

        base_half = max(0.001, self.spread / 2)
        if metrics.get("wide_spread") and metrics.get("spread"):
            base_half = min(base_half, metrics["spread"] * self.inside_spread_ratio / 2)

        skew = metrics.get("imbalance", 0.0) * self.inventory_skew * base_half
        my_bid = round(mid - base_half - skew, 3)
        my_ask = round(mid + base_half - skew, 3)

        if my_bid <= 0 or my_ask >= 1.0 or my_bid >= my_ask:
            return None

        my_bid = min(my_bid, ba - 0.001)
        my_ask = max(my_ask, bb + 0.001)

        return my_bid, my_ask

    def _score_opportunity(self, metrics: Dict) -> float:
        spread_edge = 0.0
        if metrics.get("spread"):
            spread_edge = min(1.0, metrics["spread"] / max(self.spread, 0.001)) * 0.5

        imbalance_edge = min(1.0, abs(metrics.get("imbalance", 0.0))) * 0.3
        momentum_edge = min(1.0, abs(metrics.get("mid_change", 0.0))) * 0.2

        return round(spread_edge + imbalance_edge + momentum_edge, 3)

    def find_opportunities(self) -> List[Dict]:
        """Rank tokens with actionable mechanics (wide spread, imbalance, or drift)."""

        ranked: List[Dict] = []
        for token_id, book in self.books.items():
            metrics = self.compute_book_metrics(token_id, book)
            if metrics["mid"] is None or metrics["spread"] is None:
                continue

            score = self._score_opportunity(metrics)
            if score < self.opportunity_score_threshold:
                continue

            mechanics = []
            if metrics["wide_spread"]:
                mechanics.append("inside-spread capture")
            if abs(metrics["imbalance"]) >= 0.25:
                mechanics.append("inventory skew")
            if abs(metrics["mid_change"]) >= 0.005:
                mechanics.append("micro-momentum follow")

            ranked.append({
                "token_id": token_id,
                "score": score,
                "mechanics": mechanics or ["steady alpha harvesting"],
                "metrics": metrics,
            })

        return sorted(ranked, key=lambda r: r["score"], reverse=True)

    async def update_quotes(self, token_id: str, mid: float, book: OrderBook):
        metrics = self.compute_book_metrics(token_id, book)
        quote = self._generate_quote_prices(token_id, mid, book, metrics)
        if not quote:
            return

        my_bid, my_ask = quote
        bb, _ = book.get_best_bid()
        ba, _ = book.get_best_ask()
        if bb is None or ba is None:
            return

        log_msg = (
            f"[QUOTE] {token_id[:10]}... | Mid: {mid:.3f} | "
            f"Market: {bb:.3f}-{ba:.3f} | Mine: {my_bid:.3f}-{my_ask:.3f}"
        )

        if self.dry_run:
            logger.info("%s (DRY)", log_msg)
        else:
            logger.info("%s (LIVE)", log_msg)
            await self.execute_quotes(token_id, my_bid, my_ask)

    async def execute_quotes(self, token_id: str, bid_price: float, ask_price: float):
        """
        Cancel previous orders and place new ones.
        This is a naive implementation (Cancel-All-Replace).
        Pro version would diff/amend.
        """
        if not self.executor:
            logger.warning("No executor configured; skipping live quote placement")
            return

        orders = self.active_orders.get(token_id, {})
        loop = asyncio.get_running_loop()

        cancel_tasks = []
        if orders.get("BID"):
            cancel_tasks.append(loop.run_in_executor(None, self.executor.cancel_order, orders["BID"]))
        if orders.get("ASK"):
            cancel_tasks.append(loop.run_in_executor(None, self.executor.cancel_order, orders["ASK"]))

        if cancel_tasks:
            await asyncio.gather(*cancel_tasks, return_exceptions=True)

        bid_oid = await loop.run_in_executor(
            None, self.executor.place_order, token_id, "BUY", bid_price, self.size
        )
        ask_oid = await loop.run_in_executor(
            None, self.executor.place_order, token_id, "SELL", ask_price, self.size
        )

        self.active_orders[token_id] = {"BID": bid_oid, "ASK": ask_oid}


if __name__ == "__main__":
    # Placeholder for potential manual testing entrypoint
    pass
