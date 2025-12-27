import asyncio
import logging
import math
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Tuple

import aiohttp

from src.core.feed import MarketDataFeed
from src.core.orderbook import OrderBook
from src.core.performance import (
    AdaptiveQuoteController,
    ExecutionHealth,
    ExecutionQualityMonitor,
    QuoteAdjustment,
)
from src.core.risk import CanaryGuard, DrawdownGuard, OperationalCircuitBreaker
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
            "book_skew": 0.05,
            "time_since_last_fill": 0.04,
            "social_burst_ratio": 0.05,
        }
        self.bias = bias
        self.learning_rate = learning_rate
        self.decay = decay
        self.min_fit_samples = min_fit_samples
        self.trained_samples = 0

    def _normalize(self, value: float) -> float:
        return max(-1.0, min(1.0, value))

    def predict(self, features: Dict[str, float]) -> float:
        prob, _ = self.predict_with_confidence(features)
        return prob

    def predict_with_confidence(self, features: Dict[str, float]) -> Tuple[float, float]:
        """Return probability and a confidence proxy based on fit progress."""

        score = self.bias
        for name, weight in self.feature_weights.items():
            contrib = self._normalize(features.get(name, 0.0))
            score += weight * contrib

        prob = 1 / (1 + math.exp(-score))
        prob = max(0.0, min(1.0, prob))

        confidence = min(1.0, self.trained_samples / max(self.min_fit_samples * 2, 1))
        return prob, confidence

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

    def set_regime(self, regime_tag: str) -> None:
        """Adjust decay depending on the detected regime."""

        if regime_tag == "volatile":
            self.decay = 0.93
        else:
            self.decay = 0.97


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
        ml_confidence_floor: float = 0.2,
        regime_spread_widen: float = 0.15,
        signal_model: Optional[SignalEnsembler] = None,
        circuit_breaker: Optional[OperationalCircuitBreaker] = None,
        canary_guard: Optional[CanaryGuard] = None,
        performance_tuner: Optional[AdaptiveQuoteController] = None,
        execution_monitor: Optional[ExecutionQualityMonitor] = None,
        drawdown_guard: Optional[DrawdownGuard] = None,
        stale_quote_seconds: float = 5.0,
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
        self.ml_confidence_floor = ml_confidence_floor
        self.regime_spread_widen = regime_spread_widen
        self.signal_model = signal_model or SignalEnsembler()
        self.operational_circuit = circuit_breaker
        self.canary_guard = canary_guard
        self.drawdown_guard = drawdown_guard
        self.performance_tuner = performance_tuner or AdaptiveQuoteController()
        self.execution_monitor = execution_monitor or ExecutionQualityMonitor()
        self.books: Dict[str, OrderBook] = {tid: OrderBook(tid) for tid in token_ids}
        self.feed = MarketDataFeed()
        self.feed.add_callback(self.on_market_update)

        # Track our open orders: TokenID -> {'BID': order_id, 'ASK': order_id}
        self.active_orders: Dict[str, Dict[str, str]] = {tid: {} for tid in token_ids}
        self.last_mid: Dict[str, float] = {}
        self.mid_history: Dict[str, Deque[float]] = {
            tid: deque(maxlen=self.volatility_window) for tid in token_ids
        }
        self.last_book_update: Dict[str, datetime] = {tid: datetime.utcnow() for tid in token_ids}
        self.social_signals: Dict[str, Dict[str, float]] = {
            tid: {"sentiment": 0.0, "buzz": 0.0, "whale_pressure": 0.0}
            for tid in token_ids
        }
        self.whale_heat: Dict[str, Deque[float]] = {tid: deque(maxlen=50) for tid in token_ids}
        self.prev_social_buzz: Dict[str, float] = {tid: 0.0 for tid in token_ids}
        self.last_fill_time: Dict[str, datetime] = {}
        self.quote_adjustments: Dict[str, QuoteAdjustment] = {tid: QuoteAdjustment() for tid in token_ids}
        self.execution_health: Dict[str, ExecutionHealth] = {tid: ExecutionHealth() for tid in token_ids}
        self.api_requests = 0
        self.api_errors = 0
        self.feed_latency_ms = 0.0
        self.stale_quote_seconds = stale_quote_seconds

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

    def record_api_call(self, success: bool, latency_ms: float = 0.0) -> None:
        """Track error-rate and latency for circuit breaker decisions."""

        self.api_requests += 1
        if not success:
            self.api_errors += 1
        self.feed_latency_ms = latency_ms

    @property
    def api_error_rate(self) -> float:
        if self.api_requests == 0:
            return 0.0
        return self.api_errors / max(self.api_requests, 1)

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

    def record_fill(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        pnl: float = 0.0,
    ) -> Optional[str]:
        """Register a fill to feed canary guardrails and ML features."""

        self.last_fill_time[token_id] = datetime.utcnow()

        if self.performance_tuner:
            notional = max(price * size, 0.0)
            slippage_ratio = abs(pnl) / notional if notional else 0.0
            self.performance_tuner.record_fill(
                token_id, latency_ms=self.feed_latency_ms, slippage=slippage_ratio
            )

        if self.execution_monitor:
            self.execution_monitor.record_fill(
                token_id,
                pnl=pnl,
                latency_ms=self.feed_latency_ms,
                slippage=abs(pnl) / max(price * size, 1e-6) if price and size else 0.0,
            )

        if self.canary_guard:
            violation = self.canary_guard.register_fill(token_id, price * size, pnl)
            if violation:
                logger.warning("[CANARY] Block due to %s on %s", violation, token_id)
            return violation
        if self.drawdown_guard:
            violation = self.drawdown_guard.register_fill(pnl)
            if violation:
                logger.warning("[DRAWDOWN] Limit reached: %s", violation)
            return violation
        return None

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
        self.last_book_update[token_id] = datetime.utcnow()
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
        self.last_book_update[token_id] = datetime.utcnow()

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
        prev_buzz = self.prev_social_buzz.get(token_id, 0.0)
        social_burst_ratio = 0.0
        if prev_buzz > 0:
            social_burst_ratio = max(0.0, (social.get("buzz", 0.0) - prev_buzz) / max(prev_buzz, 0.1))
        self.prev_social_buzz[token_id] = social.get("buzz", 0.0)
        whale_shadow = self._compute_whale_shadow(token_id)
        last_fill_at = self.last_fill_time.get(token_id)
        time_since_last_fill = (
            (datetime.utcnow() - last_fill_at).total_seconds() if last_fill_at else float("inf")
        )
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
            "time_since_last_fill": time_since_last_fill,
            "social_burst_ratio": social_burst_ratio,
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

    def _detect_regime(self, metrics: Dict) -> Dict[str, float]:
        """Infer a coarse market regime to adapt width and leaning."""

        volatility = metrics.get("volatility", 0.0)
        trend = metrics.get("micro_trend", 0.0)
        whale_shadow = metrics.get("whale_shadow_bias", 0.0)
        whale_pressure = metrics.get("whale_pressure", 0.0)
        social_buzz = metrics.get("social_buzz", 0.0)
        social_sentiment = metrics.get("social_sentiment", 0.0)

        widen = 0.0
        lean = 0.0
        tag = "normal"

        if volatility >= self.volatility_threshold * 1.5 or abs(trend) >= self.trend_threshold * 1.5:
            widen = max(widen, self.regime_spread_widen)
            tag = "volatile" if abs(trend) < self.trend_threshold * 1.5 else "drifting"

        if social_buzz >= 0.7:
            widen = max(widen, self.regime_spread_widen * 0.6)
            lean += social_sentiment * 0.3
            tag = "social-buzz"

        if abs(whale_shadow) >= 0.5 or whale_pressure >= 0.6:
            widen = max(widen, self.regime_spread_widen * 0.9)
            lean += whale_shadow * 0.5
            tag = "whale-burst"

        return {"tag": tag, "widen": widen, "lean": lean}

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

        if self.operational_circuit:
            cb_status = self.operational_circuit.evaluate(
                volatility=volatility,
                baseline_volatility=self.volatility_threshold,
                error_rate=self.api_error_rate,
                latency_ms=self.feed_latency_ms,
            )
            if cb_status.active:
                return True, f"circuit_breaker:{cb_status.reason}"

        return False, None

    def _generate_quote_prices(
        self, token_id: str, mid: float, book: OrderBook, metrics: Optional[Dict] = None
    ) -> Optional[Tuple[float, float]]:
        metrics = metrics or self.compute_book_metrics(token_id, book)
        last_update = self.last_book_update.get(token_id, datetime.utcnow())
        if (datetime.utcnow() - last_update).total_seconds() > self.stale_quote_seconds:
            logger.info("[PAUSE] Stale book for %s; skipping quotes", token_id)
            return None
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

        adjustment = QuoteAdjustment()
        if self.performance_tuner:
            adjustment = self.performance_tuner.compute_adjustment(
                token_id,
                volatility=volatility,
                latency_ms=self.feed_latency_ms,
            )
            base_half *= 1 + adjustment.spread_widen
        self.quote_adjustments[token_id] = adjustment

        health = None
        if self.execution_monitor:
            health = self.execution_monitor.evaluate(token_id)
            self.execution_health[token_id] = health
            if health.status == "halt":
                logger.warning(
                    "[QUALITY] Halting quotes for %s due to %s", token_id, health.reason
                )
                return None
            if health.spread_penalty:
                base_half *= 1 + health.spread_penalty

        trend_bias = metrics.get("micro_trend", 0.0)
        trend_skew = trend_bias * self.inside_spread_ratio * base_half

        social_sentiment = metrics.get("social_sentiment", 0.0)
        social_buzz = metrics.get("social_buzz", 0.0)
        whale_pressure = metrics.get("whale_pressure", 0.0)
        whale_shadow = metrics.get("whale_shadow_bias", 0.0)
        regime = self._detect_regime(metrics)

        base_half *= 1 + social_buzz * 0.1
        base_half *= 1 + whale_pressure * self.whale_pressure_widen
        base_half *= 1 + abs(whale_shadow) * 0.1
        base_half *= 1 + regime.get("widen", 0.0)

        sentiment_skew = social_sentiment * self.social_sentiment_bias * base_half * 0.5
        shadow_skew = whale_shadow * base_half * 0.35
        regime_skew = regime.get("lean", 0.0) * base_half * 0.5

        skew = metrics.get("imbalance", 0.0) * self.inventory_skew * base_half
        my_bid = round(mid - base_half - skew - trend_skew + sentiment_skew + shadow_skew + regime_skew, 3)
        my_ask = round(mid + base_half - skew - trend_skew + sentiment_skew + shadow_skew + regime_skew, 3)

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

        regime = self._detect_regime(metrics)
        regime_edge = 0.05 if regime.get("tag") != "normal" else 0.0

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
            + shadow_edge
            + regime_edge,
            3,
        )

        ml_score = 0.0
        ml_conf = 0.0
        regime = self._detect_regime(metrics)
        if self.signal_model:
            self.signal_model.set_regime(regime.get("tag"))
        if self.signal_model:
            ml_features = self._build_ml_features(metrics)
            ml_score, ml_conf = self.signal_model.predict_with_confidence(ml_features)

        whale_pressure = metrics.get("whale_pressure", 0.0)
        whale_gate = 1.2 if whale_pressure >= 0.55 else 0.6
        effective_weight = self.ml_edge_weight * max(self.ml_confidence_floor, ml_conf) * whale_gate
        effective_weight = min(0.95, effective_weight)
        combo = heuristic_score * (1 - effective_weight) + ml_score * effective_weight
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
            "book_skew": metrics.get("imbalance", 0.0),
            "time_since_last_fill": metrics.get("time_since_last_fill", 0.0),
            "social_burst_ratio": metrics.get("social_burst_ratio", 0.0),
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
            regime = self._detect_regime(metrics)
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
            if regime.get("tag") == "whale-burst":
                mechanics.append("whale burst chase")
            if regime.get("tag") == "social-buzz":
                mechanics.append("buzz echo capture")
            if regime.get("tag") in {"volatile", "drifting"}:
                mechanics.append("regime-aware sheltering")
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
        adjustment = self.quote_adjustments.get(token_id, QuoteAdjustment())
        health = self.execution_health.get(token_id)
        health_size_multiplier = health.size_multiplier if health else 1.0
        quote_size = max(0.001, self.size * adjustment.size_multiplier * health_size_multiplier)
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
            if self.canary_guard:
                notional = max(mid, 0.0) * quote_size
                violation = self.canary_guard.check_order(token_id, notional)
                if violation:
                    logger.warning("[CANARY] Skipping live quotes for %s due to %s", token_id, violation)
                    return
            if self.drawdown_guard:
                violation = self.drawdown_guard.check_equity(self.drawdown_guard.current_equity)
                if violation:
                    logger.warning("[DRAWDOWN] Halting quotes for %s due to %s", token_id, violation)
                    return
            logger.info("%s (LIVE)", log_msg)
            await self.execute_quotes(token_id, my_bid, my_ask, size=quote_size)

    async def execute_quotes(
        self, token_id: str, bid_price: float, ask_price: float, *, size: Optional[float] = None
    ):
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

        chosen_size = self.size if size is None else size

        bid_oid = await loop.run_in_executor(
            None, self.executor.place_order, token_id, "BUY", bid_price, chosen_size
        )
        ask_oid = await loop.run_in_executor(
            None, self.executor.place_order, token_id, "SELL", ask_price, chosen_size
        )

        self.active_orders[token_id] = {"BID": bid_oid, "ASK": ask_oid}


if __name__ == "__main__":
    # Placeholder for potential manual testing entrypoint
    pass
