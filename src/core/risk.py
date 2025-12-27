import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerStatus:
    """Represents the current trip status of an operational circuit breaker."""

    tripped: bool
    reason: Optional[str] = None
    until: Optional[datetime] = None

    @property
    def active(self) -> bool:
        return self.tripped and (self.until is None or datetime.utcnow() <= self.until)


class OperationalCircuitBreaker:
    """Circuit breaker for volatility, error-rate, and latency protection.

    This class centralizes the protective logic described in the rollout plan:
    - Pause quoting if volatility exceeds a configured multiple of the baseline.
    - Pause if API error-rate crosses a ceiling within the recent window.
    - Pause if feed latency degrades persistently beyond an acceptable bound.
    """

    def __init__(
        self,
        volatility_multiple: float = 2.0,
        error_rate_ceiling: float = 0.05,
        latency_ceiling_ms: float = 250.0,
        cooldown_seconds: int = 300,
    ) -> None:
        self.volatility_multiple = volatility_multiple
        self.error_rate_ceiling = error_rate_ceiling
        self.latency_ceiling_ms = latency_ceiling_ms
        self.cooldown = timedelta(seconds=cooldown_seconds)
        self._status: CircuitBreakerStatus = CircuitBreakerStatus(tripped=False)

    @property
    def status(self) -> CircuitBreakerStatus:
        # If cooldown expired, automatically reset
        if self._status.tripped and self._status.until and datetime.utcnow() > self._status.until:
            self._status = CircuitBreakerStatus(tripped=False)
        return self._status

    def evaluate(
        self,
        volatility: float,
        baseline_volatility: float,
        error_rate: float,
        latency_ms: float,
    ) -> CircuitBreakerStatus:
        if self.status.active:
            return self.status

        reasons = []
        if baseline_volatility > 0 and volatility >= baseline_volatility * self.volatility_multiple:
            reasons.append("volatility")

        if error_rate >= self.error_rate_ceiling:
            reasons.append("error_rate")

        if latency_ms >= self.latency_ceiling_ms:
            reasons.append("latency")

        if reasons:
            reason = ",".join(sorted(reasons))
            self._status = CircuitBreakerStatus(
                tripped=True, reason=reason, until=datetime.utcnow() + self.cooldown
            )
            logger.warning("[CB] Tripped due to %s; cooling down for %ss", reason, self.cooldown.seconds)

        return self.status


class CanaryGuard:
    """Implements go-live guardrails for canary mode.

    Tracks daily notional, per-token limits, and consecutive losses. When any
    limit is violated the guard reports a block so the caller can halt live trading.
    """

    def __init__(
        self,
        per_token_notional: float = 150.0,
        daily_notional_limit: float = 800.0,
        max_consecutive_losses: int = 3,
    ) -> None:
        self.per_token_notional = per_token_notional
        self.daily_notional_limit = daily_notional_limit
        self.max_consecutive_losses = max_consecutive_losses
        self.daily_total = 0.0
        self.consecutive_losses = 0
        self.last_reset = datetime.utcnow().date()
        self.per_token_usage = {}  # token_id -> notional traded today

    def _maybe_reset(self) -> None:
        today = datetime.utcnow().date()
        if today != self.last_reset:
            self.daily_total = 0.0
            self.consecutive_losses = 0
            self.per_token_usage = {}
            self.last_reset = today

    def check_order(self, token_id: str, notional: float) -> Optional[str]:
        """Pre-flight check before placing live orders."""

        self._maybe_reset()

        projected_daily = self.daily_total + abs(notional)
        projected_token = self.per_token_usage.get(token_id, 0.0) + abs(notional)

        if projected_token > self.per_token_notional:
            return "per_token_limit"
        if projected_daily > self.daily_notional_limit:
            return "daily_limit"
        if self.consecutive_losses > self.max_consecutive_losses:
            return "consecutive_losses"
        return None

    def register_fill(self, token_id: str, notional: float, pnl: float) -> Optional[str]:
        """Record a live fill and return a violation reason if limits are crossed."""

        self._maybe_reset()

        self.daily_total += abs(notional)
        self.per_token_usage[token_id] = self.per_token_usage.get(token_id, 0.0) + abs(notional)

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        if self.per_token_usage[token_id] > self.per_token_notional:
            return "per_token_limit"
        if self.daily_total > self.daily_notional_limit:
            return "daily_limit"
        if self.consecutive_losses > self.max_consecutive_losses:
            return "consecutive_losses"

        return None


class DrawdownGuard:
    """Tracks PnL-driven risk limits to halt trading on drawdowns or daily losses."""

    def __init__(
        self,
        starting_equity: float = 1000.0,
        *,
        max_daily_loss: float = 200.0,
        max_drawdown_pct: float = 0.15,
    ) -> None:
        self.starting_equity = starting_equity
        self.max_daily_loss = max_daily_loss
        self.max_drawdown_pct = max_drawdown_pct

        self.current_equity = starting_equity
        self.peak_equity = starting_equity
        self.daily_pnl = 0.0
        self.last_reset = datetime.utcnow().date()

    def _maybe_reset(self) -> None:
        today = datetime.utcnow().date()
        if today != self.last_reset:
            self.daily_pnl = 0.0
            self.peak_equity = self.current_equity
            self.last_reset = today

    def register_fill(self, pnl: float) -> Optional[str]:
        """Update equity state and return a violation reason when limits breach."""

        self._maybe_reset()

        self.current_equity += pnl
        self.daily_pnl += pnl
        self.peak_equity = max(self.peak_equity, self.current_equity)

        drawdown = 0.0
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - self.current_equity) / self.peak_equity

        if self.daily_pnl <= -abs(self.max_daily_loss):
            return "daily_loss_limit"
        if drawdown >= self.max_drawdown_pct:
            return "drawdown_limit"
        return None

    def check_equity(self, equity: float) -> Optional[str]:
        """Allow external components to update equity snapshots and enforce limits."""

        self._maybe_reset()

        self.current_equity = equity
        self.peak_equity = max(self.peak_equity, equity)

        drawdown = 0.0
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - self.current_equity) / self.peak_equity

        if self.daily_pnl <= -abs(self.max_daily_loss):
            return "daily_loss_limit"
        if drawdown >= self.max_drawdown_pct:
            return "drawdown_limit"
        return None

