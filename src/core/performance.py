from dataclasses import dataclass
from typing import Dict


@dataclass
class QuoteAdjustment:
    """Represents dynamic sizing and spread tweaks for quoting.

    Attributes:
        size_multiplier: Factor applied to the strategy base size.
        spread_widen: Proportional widening (+) or tightening (-) of half-spread.
    """

    size_multiplier: float = 1.0
    spread_widen: float = 0.0


@dataclass
class ExecutionHealth:
    """Summarizes current execution quality for a token.

    Attributes:
        status: "healthy", "degraded", or "halt" to gate quoting aggressiveness.
        reason: Human-readable reason for the current status.
        spread_penalty: Additional widening factor applied to half-spread.
        size_multiplier: Multiplier applied to quote size for live trading.
    """

    status: str = "healthy"
    reason: str = ""
    spread_penalty: float = 0.0
    size_multiplier: float = 1.0


class AdaptiveQuoteController:
    """Learns lightweight execution feedback loops to tune size and spread.

    The controller smooths fill-rate, latency, and slippage to:
    - widen quotes during volatility, latency spikes, or poor execution quality;
    - tighten and scale up when fill-rate is healthy without adverse slippage.
    This mirrors the performance-tuning steps outlined in the rollout plan
    without requiring heavy dependencies.
    """

    def __init__(
        self,
        *,
        smoothing: float = 0.2,
        target_fill_rate: float = 0.6,
        volatility_threshold: float = 0.01,
        latency_threshold_ms: float = 350.0,
        slippage_threshold: float = 0.01,
        min_size_multiplier: float = 0.5,
        max_size_multiplier: float = 1.8,
    ) -> None:
        self.smoothing = smoothing
        self.target_fill_rate = target_fill_rate
        self.volatility_threshold = volatility_threshold
        self.latency_threshold_ms = latency_threshold_ms
        self.slippage_threshold = slippage_threshold
        self.min_size_multiplier = min_size_multiplier
        self.max_size_multiplier = max_size_multiplier

        self.fill_rate: Dict[str, float] = {}
        self.avg_latency: Dict[str, float] = {}
        self.avg_slippage: Dict[str, float] = {}

    def _smooth(self, store: Dict[str, float], key: str, value: float) -> float:
        prior = store.get(key, value)
        updated = prior * (1 - self.smoothing) + value * self.smoothing
        store[key] = updated
        return updated

    def record_fill(
        self,
        token_id: str,
        *,
        filled: bool = True,
        latency_ms: float = 0.0,
        slippage: float = 0.0,
    ) -> None:
        """Update smoothed execution quality metrics."""

        hit = 1.0 if filled else 0.0
        self._smooth(self.fill_rate, token_id, hit)
        self._smooth(self.avg_latency, token_id, max(latency_ms, 0.0))
        self._smooth(self.avg_slippage, token_id, max(slippage, 0.0))

    def compute_adjustment(
        self, token_id: str, *, volatility: float = 0.0, latency_ms: float = 0.0
    ) -> QuoteAdjustment:
        """Derive size/spread multipliers from execution telemetry."""

        fill_rate = self.fill_rate.get(token_id)
        if fill_rate is None:
            return QuoteAdjustment()

        avg_latency = self.avg_latency.get(token_id, 0.0)
        avg_slippage = self.avg_slippage.get(token_id, 0.0)

        adjust = QuoteAdjustment()

        # Reward healthy fill-rate by tightening slightly and scaling size
        if fill_rate > self.target_fill_rate and avg_slippage <= self.slippage_threshold:
            adjust.spread_widen -= min(
                0.15,
                (fill_rate - self.target_fill_rate) / max(self.target_fill_rate, 1e-6) * 0.1,
            )
            adjust.size_multiplier += min(
                self.max_size_multiplier - 1.0, fill_rate * 0.35
            )

        # Penalize low fill-rate by widening until the book becomes more aggressive again
        if fill_rate < self.target_fill_rate * 0.6:
            adjust.spread_widen += 0.08
            adjust.size_multiplier -= 0.1

        # Volatility and latency explicitly widen to avoid adverse selection
        if volatility > self.volatility_threshold:
            vol_over = (volatility - self.volatility_threshold) / max(
                self.volatility_threshold, 1e-6
            )
            adjust.spread_widen += min(0.3, vol_over * 0.05)

        effective_latency = max(latency_ms, avg_latency)
        if effective_latency > self.latency_threshold_ms:
            adjust.spread_widen += 0.05
            adjust.size_multiplier -= 0.1

        if avg_slippage > self.slippage_threshold:
            adjust.spread_widen += 0.06
            adjust.size_multiplier -= 0.05

        adjust.spread_widen = max(-0.2, min(0.4, adjust.spread_widen))
        adjust.size_multiplier = max(
            self.min_size_multiplier, min(self.max_size_multiplier, adjust.size_multiplier)
        )
        return adjust

    def apply_size(self, token_id: str, base_size: float) -> float:
        adjustment = self.compute_adjustment(token_id)
        return max(0.0, base_size * adjustment.size_multiplier)


class ExecutionQualityMonitor:
    """Tracks execution health to gracefully degrade or halt quoting.

    The monitor smooths win-rate, latency, slippage, and loss streaks to derive
    a coarse "health" state that can widen quotes or block live placement when
    execution quality deteriorates.
    """

    def __init__(
        self,
        *,
        smoothing: float = 0.3,
        warn_slippage: float = 0.02,
        halt_slippage: float = 0.05,
        warn_latency_ms: float = 350.0,
        halt_latency_ms: float = 900.0,
        min_win_rate: float = 0.45,
        halt_loss_streak: int = 4,
    ) -> None:
        self.smoothing = smoothing
        self.warn_slippage = warn_slippage
        self.halt_slippage = halt_slippage
        self.warn_latency_ms = warn_latency_ms
        self.halt_latency_ms = halt_latency_ms
        self.min_win_rate = min_win_rate
        self.halt_loss_streak = halt_loss_streak

        self.win_rate: Dict[str, float] = {}
        self.avg_latency: Dict[str, float] = {}
        self.avg_slippage: Dict[str, float] = {}
        self.loss_streak: Dict[str, int] = {}

    def _smooth(self, store: Dict[str, float], key: str, value: float) -> float:
        prior = store.get(key, value)
        updated = prior * (1 - self.smoothing) + value * self.smoothing
        store[key] = updated
        return updated

    def record_fill(
        self,
        token_id: str,
        *,
        pnl: float,
        latency_ms: float,
        slippage: float,
    ) -> None:
        """Update rolling execution quality statistics for a token."""

        hit = 1.0 if pnl >= 0 else 0.0
        self._smooth(self.win_rate, token_id, hit)
        self._smooth(self.avg_latency, token_id, max(latency_ms, 0.0))
        self._smooth(self.avg_slippage, token_id, max(slippage, 0.0))

        streak = self.loss_streak.get(token_id, 0)
        if pnl < 0:
            streak += 1
        else:
            streak = 0
        self.loss_streak[token_id] = streak

    def evaluate(self, token_id: str) -> ExecutionHealth:
        """Return current execution health and guidance for quoting."""

        win_rate = self.win_rate.get(token_id, 1.0)
        latency = self.avg_latency.get(token_id, 0.0)
        slippage = self.avg_slippage.get(token_id, 0.0)
        losses = self.loss_streak.get(token_id, 0)

        reasons = []
        status = "healthy"
        spread_penalty = 0.0
        size_multiplier = 1.0

        if slippage >= self.halt_slippage:
            reasons.append("slippage")
            status = "halt"
        if latency >= self.halt_latency_ms:
            reasons.append("latency")
            status = "halt"
        if losses >= self.halt_loss_streak:
            reasons.append("loss_streak")
            status = "halt"

        if status != "halt":
            if win_rate < self.min_win_rate or slippage >= self.warn_slippage or latency >= self.warn_latency_ms:
                status = "degraded"
                if slippage >= self.warn_slippage:
                    reasons.append("slippage")
                if latency >= self.warn_latency_ms:
                    reasons.append("latency")
                if win_rate < self.min_win_rate:
                    reasons.append("win_rate")
                spread_penalty = 0.12
                size_multiplier = 0.7

        if status == "halt":
            spread_penalty = 0.35
            size_multiplier = 0.0

        return ExecutionHealth(
            status=status,
            reason=",".join(sorted(set(reasons))),
            spread_penalty=spread_penalty,
            size_multiplier=size_multiplier,
        )

    def reset(self, token_id: str) -> None:
        self.win_rate.pop(token_id, None)
        self.avg_latency.pop(token_id, None)
        self.avg_slippage.pop(token_id, None)
        self.loss_streak.pop(token_id, None)
