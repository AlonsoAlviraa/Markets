import asyncio
import logging
import math
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import aiohttp

from src.core.feed import MarketDataFeed
from src.core.orderbook import OrderBook
from src.exchanges.polymarket_clob import PolymarketOrderExecutor

logger = logging.getLogger(__name__)


class SignalEnsembler:
    """Lightweight online learner to blend book, trend, and whale signals.

    This avoids heavyweight ML deps while still allowing us to fit signal weights
    from labeled examples and produce a smooth 0-1 edge score.
    """

    def __init__(
        self,
        feature_weights: Optional[Dict[str, float]] = None,
        bias: float = 0.05,
        learning_rate: float = 0.25,
        decay: float = 0.97,
        min_fit_samples: int = 5,
    ):
        self.feature_weights = feature_weights or {
            "spread": 0.08,
            "imbalance": 0.14,
            "volatility": 0.06,
            "micro_trend": 0.08,
            "liquidity_vacuum": 0.05,
            "whale_pressure": 0.12,
            "social_buzz": 0.05,
            "whale_shadow_bias": 0.1,
        }
        self.bias = bias
        self.learning_rate = learning_rate
        self.decay = decay
        self.min_fit_samples = min_fit_samples
        self.trained_samples = 0

    def _normalize(self, value: float) -> float:
        return max(-1.0, min(1.0, value))

    def predict(self, features: Dict[str, float]) -> float:
        score = self.bias
        for name, weight in self.feature_weights.items():
            contrib = self._normalize(features.get(name, 0.0))
            score += weight * contrib

        prob = 1 / (1 + math.exp(-score))
        return max(0.0, min(1.0, prob))

    def fit(self, labeled_samples: List[Dict[str, Dict[str, float]]]) -> None:
        """Update weights using simple online gradient steps.

        Each sample is {"features": {...}, "label": float 0-1}.
        """

        if not labeled_samples:
            return

        for sample in labeled_samples:
            features = sample.get("features", {})
            label = max(0.0, min(1.0, float(sample.get("label", 0.0))))
            pred = self.predict(features)
            error = label - pred
            for name, weight in self.feature_weights.items():
                feat = self._normalize(features.get(name, 0.0))
                self.feature_weights[name] = weight * self.decay + self.learning_rate * error * feat

            self.bias = self.bias * self.decay + self.learning_rate * error * 0.1
            self.trained_samples += 1

    @property
    def ready(self) -> bool:
        return self.trained_samples >= self.min_fit_samples


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
        volatility_window: int = 12,
        volatility_threshold: float = 0.01,
        momentum_window: int = 5,
        trend_threshold: float = 0.004,
        vacuum_depth_threshold: float = 0.2,
        risk_pause_vol_multiplier: float = 2.5,
        risk_pause_trend_multiplier: float = 2.0,
        social_sentiment_bias: float = 0.5,
        whale_pressure_widen: float = 0.2,
        ml_edge_weight: float = 0.35,
        signal_model: Optional[SignalEnsembler] = None,
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
        self.volatility_window = max(3, volatility_window)
        self.volatility_threshold = volatility_threshold
        self.momentum_window = max(2, momentum_window)
        self.trend_threshold = trend_threshold
        self.vacuum_depth_threshold = vacuum_depth_threshold
        self.risk_pause_vol_multiplier = risk_pause_vol_multiplier
        self.risk_pause_trend_multiplier = risk_pause_trend_multiplier
        self.social_sentiment_bias = social_sentiment_bias
        self.whale_pressure_widen = whale_pressure_widen
        self.ml_edge_weight = ml_edge_weight
        self.signal_model = signal_model or SignalEnsembler()
        self.books: Dict[str, OrderBook] = {tid: OrderBook(tid) for tid in token_ids}
        self.feed = MarketDataFeed()
        self.feed.add_callback(self.on_market_update)

        # Track our open orders: TokenID -> {'BID': order_id, 'ASK': order_id}
        self.active_orders: Dict[str, Dict[str, str]] = {tid: {} for tid in token_ids}
        self.last_mid: Dict[str, float] = {}
        self.mid_history: Dict[str, Deque[float]] = {
            tid: deque(maxlen=self.volatility_window) for tid in token_ids
        }
        self.social_signals: Dict[str, Dict[str, float]] = {
            tid: {"sentiment": 0.0, "buzz": 0.0, "whale_pressure": 0.0}
            for tid in token_ids
        }
        self.whale_heat: Dict[str, Deque[float]] = {tid: deque(maxlen=50) for tid in token_ids}

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
            await asyncio.sleep(1)

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

    def ingest_social_signal(
        self,
        token_id: str,
        sentiment: float = 0.0,
        buzz: float = 0.0,
        whale_pressure: float = 0.0,
    ) -> None:
        """Record social sentiment/buzz signals and whale pressure for a token.

        Values are clamped to [0, 1] for buzz/whale_pressure and [-1, 1] for sentiment.
        """

        if token_id not in self.social_signals:
            logger.debug("[SOCIAL] Ignoring signal for unknown token %s", token_id)
            return

        sanitized = {
            "sentiment": max(-1.0, min(1.0, sentiment)),
            "buzz": max(0.0, min(1.0, buzz)),
            "whale_pressure": max(0.0, min(1.0, whale_pressure)),
        }
        self.social_signals[token_id].update(sanitized)

    def record_whale_action(
        self,
        token_id: str,
        side: str,
        size: float,
        confidence: float = 0.5,
    ) -> None:
        """Track signed whale flow to bias quoting and ML signals.

        Side is BUY/SELL. Confidence and size modulate intensity and also feed back
        into whale_pressure for compatibility with prior logic.
        """

        if token_id not in self.whale_heat:
            return

        signed = 1.0 if side.upper() == "BUY" else -1.0
        intensity = max(0.0, min(1.0, confidence)) * min(1.0, size / max(self.size, 1e-6))
        weighted = signed * intensity
        self.whale_heat[token_id].append(weighted)

        whale_pressure = max(0.0, sum(self.whale_heat[token_id]) / len(self.whale_heat[token_id]))
        self.social_signals[token_id]["whale_pressure"] = whale_pressure

    def train_signal_model(self, labeled_samples: List[Dict[str, Dict[str, float]]]) -> None:
        """Allow external processes to fit the online ensembler."""

        if not self.signal_model:
            return
        self.signal_model.fit(labeled_samples)

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
        bb, bb_size = book.get_best_bid()
        ba, ba_size = book.get_best_ask()
        mid = book.get_mid_price()
        spread = book.get_spread()

        bid_depth = sum(book.bids.values())
        ask_depth = sum(book.asks.values())
        total_depth = bid_depth + ask_depth
        imbalance = 0.0
        top_depth_share = 0.0
        if total_depth > 0:
            imbalance = (bid_depth - ask_depth) / total_depth
            top_depth_share = (bb_size + ba_size) / total_depth

        prev_mid = self.last_mid.get(token_id, mid or 0.0)
        mid_change = (mid or prev_mid) - prev_mid

        if mid is not None:
            self._record_mid(token_id, mid)
            self.last_mid[token_id] = mid

        volatility = self._compute_volatility(token_id)
        trend = self._compute_trend(token_id)
        social = self.social_signals.get(
            token_id, {"sentiment": 0.0, "buzz": 0.0, "whale_pressure": 0.0}
        )
        whale_shadow = self._compute_whale_shadow(token_id)
        metrics = {
            "mid": mid,
            "spread": spread,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "imbalance": imbalance,
            "wide_spread": bool(spread is not None and spread >= self.wide_spread_threshold),
            "mid_change": mid_change,
            "volatility": volatility,
            "micro_trend": trend,
            "top_depth_share": top_depth_share,
            "liquidity_vacuum": bool(top_depth_share <= self.vacuum_depth_threshold),
            "social_sentiment": social.get("sentiment", 0.0),
            "social_buzz": social.get("buzz", 0.0),
            "whale_pressure": social.get("whale_pressure", 0.0),
            "whale_shadow_bias": whale_shadow,
        }

        return metrics

    def _record_mid(self, token_id: str, mid: float):
        history = self.mid_history.setdefault(token_id, deque(maxlen=self.volatility_window))
        history.append(mid)

    def _compute_volatility(self, token_id: str) -> float:
        history = self.mid_history.get(token_id, deque())
        if len(history) < 2:
            return 0.0
        mean = sum(history) / len(history)
        variance = sum((p - mean) ** 2 for p in history) / len(history)
        return round(variance**0.5, 6)

    def _compute_trend(self, token_id: str) -> float:
        history = self.mid_history.get(token_id, deque())
        if len(history) < 2:
            return 0.0
        window = list(history)[-self.momentum_window :]
        if len(window) < 2 or window[0] == 0:
            return 0.0
        return round((window[-1] - window[0]) / window[0], 6)

    def _compute_whale_shadow(self, token_id: str) -> float:
        flow = self.whale_heat.get(token_id)
        if not flow:
            return 0.0

        avg_flow = sum(flow) / len(flow)
        return round(max(-1.0, min(1.0, avg_flow)), 4)

    def _should_pause_quotes(self, metrics: Dict) -> Tuple[bool, Optional[str]]:
        volatility = metrics.get("volatility", 0.0)
        trend = abs(metrics.get("micro_trend", 0.0))

        extreme_vol = volatility >= self.volatility_threshold * self.risk_pause_vol_multiplier
        extreme_trend = trend >= self.trend_threshold * self.risk_pause_trend_multiplier

        if extreme_vol and extreme_trend:
            return True, "volatility_and_trend"
        if extreme_vol:
            return True, "volatility"
        if extreme_trend:
            return True, "trend"

        return False, None

    def _generate_quote_prices(
        self, token_id: str, mid: float, book: OrderBook, metrics: Optional[Dict] = None
    ) -> Optional[Tuple[float, float]]:
        metrics = metrics or self.compute_book_metrics(token_id, book)
        should_pause, pause_reason = self._should_pause_quotes(metrics)
        if should_pause:
            logger.info(
                "[PAUSE] Skipping quotes due to %s | vol=%.4f trend=%.4f",
                pause_reason,
                metrics.get("volatility", 0.0),
                metrics.get("micro_trend", 0.0),
            )
            return None

        bb, _ = book.get_best_bid()
        ba, _ = book.get_best_ask()

        if bb is None or ba is None:
            return None

        base_half = max(0.001, self.spread / 2)
        if metrics.get("wide_spread") and metrics.get("spread"):
            base_half = min(base_half, metrics["spread"] * self.inside_spread_ratio / 2)

        volatility = metrics.get("volatility", 0.0)
        if volatility > self.volatility_threshold:
            vol_ratio = min(3.0, (volatility - self.volatility_threshold) / max(self.volatility_threshold, 1e-6))
            base_half *= 1 + vol_ratio * 0.15

        trend_bias = metrics.get("micro_trend", 0.0)
        trend_skew = trend_bias * self.inside_spread_ratio * base_half

        social_sentiment = metrics.get("social_sentiment", 0.0)
        social_buzz = metrics.get("social_buzz", 0.0)
        whale_pressure = metrics.get("whale_pressure", 0.0)
        whale_shadow = metrics.get("whale_shadow_bias", 0.0)

        base_half *= 1 + social_buzz * 0.1
        base_half *= 1 + whale_pressure * self.whale_pressure_widen
        base_half *= 1 + abs(whale_shadow) * 0.1

        sentiment_skew = social_sentiment * self.social_sentiment_bias * base_half * 0.5
        shadow_skew = whale_shadow * base_half * 0.35

        skew = metrics.get("imbalance", 0.0) * self.inventory_skew * base_half
        my_bid = round(mid - base_half - skew - trend_skew + sentiment_skew + shadow_skew, 3)
        my_ask = round(mid + base_half - skew - trend_skew + sentiment_skew + shadow_skew, 3)

        if my_bid <= 0 or my_ask >= 1.0 or my_bid >= my_ask:
            return None

        my_bid = min(my_bid, ba - 0.001)
        my_ask = max(my_ask, bb + 0.001)

        return my_bid, my_ask

    def _score_opportunity(self, metrics: Dict) -> float:
        spread_edge = 0.0
        if metrics.get("spread"):
            spread_edge = min(1.0, metrics["spread"] / max(self.spread, 0.001)) * 0.5

        imbalance_edge = min(1.0, abs(metrics.get("imbalance", 0.0))) * 0.25
        momentum_edge = min(1.0, abs(metrics.get("mid_change", 0.0))) * 0.08
        volatility_edge = min(1.0, metrics.get("volatility", 0.0) / max(self.volatility_threshold, 1e-6)) * 0.07
        vacuum_edge = 0.07 if metrics.get("liquidity_vacuum") else 0.0
        trend_edge = min(1.0, abs(metrics.get("micro_trend", 0.0)) / max(self.trend_threshold, 1e-6)) * 0.08
        depth_edge = min(1.0, max(0.0, 1 - metrics.get("top_depth_share", 0.0))) * 0.05
        sentiment_edge = min(1.0, abs(metrics.get("social_sentiment", 0.0))) * 0.05
        buzz_edge = min(1.0, metrics.get("social_buzz", 0.0)) * 0.05
        whale_edge = min(1.0, metrics.get("whale_pressure", 0.0)) * 0.05
        shadow_edge = min(1.0, abs(metrics.get("whale_shadow_bias", 0.0))) * 0.06

        heuristic_score = round(
            spread_edge
            + imbalance_edge
            + momentum_edge
            + volatility_edge
            + vacuum_edge
            + trend_edge
            + depth_edge
            + sentiment_edge
            + buzz_edge
            + whale_edge
            + shadow_edge,
            3,
        )

        ml_score = 0.0
        if self.signal_model:
            ml_features = self._build_ml_features(metrics)
            ml_score = self.signal_model.predict(ml_features)

        combo = heuristic_score * (1 - self.ml_edge_weight) + ml_score * self.ml_edge_weight
        return round(min(1.0, combo), 3)

    def _build_ml_features(self, metrics: Dict) -> Dict[str, float]:
        return {
            "spread": metrics.get("spread", 0.0),
            "imbalance": metrics.get("imbalance", 0.0),
            "volatility": metrics.get("volatility", 0.0),
            "micro_trend": metrics.get("micro_trend", 0.0),
            "liquidity_vacuum": 1.0 if metrics.get("liquidity_vacuum") else 0.0,
            "whale_pressure": metrics.get("whale_pressure", 0.0),
            "social_buzz": metrics.get("social_buzz", 0.0),
            "whale_shadow_bias": metrics.get("whale_shadow_bias", 0.0),
        }

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
            if metrics.get("liquidity_vacuum"):
                mechanics.append("liquidity vacuum sniping")
            if metrics.get("volatility", 0.0) >= self.volatility_threshold:
                mechanics.append("volatility breakout capture")
            if abs(metrics.get("micro_trend", 0.0)) >= self.trend_threshold:
                mechanics.append("trend leaning")
            if metrics.get("volatility", 0.0) >= self.volatility_threshold * self.risk_pause_vol_multiplier:
                mechanics.append("volatility retreat")
            if metrics.get("liquidity_vacuum") and metrics.get("spread", 0) >= self.wide_spread_threshold * 1.5:
                mechanics.append("vacuum wide staggering")
            if metrics.get("social_buzz", 0.0) >= 0.6:
                mechanics.append("social buzz momentum")
            if abs(metrics.get("social_sentiment", 0.0)) >= 0.5:
                mechanics.append("sentiment leaning")
            if metrics.get("whale_pressure", 0.0) >= 0.5:
                mechanics.append("whale shadowing")
            if abs(metrics.get("whale_shadow_bias", 0.0)) >= 0.3:
                mechanics.append("alpha wallet shadow")
            if self.signal_model and self.signal_model.ready:
                mechanics.append("ml edge confirmation")

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
