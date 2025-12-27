import math
import os
import sys

sys.path.append(os.path.abspath("."))

from src.core.orderbook import OrderBook
from src.core.performance import ExecutionQualityMonitor
from src.strategies.market_maker import SimpleMarketMaker


def build_basic_book() -> OrderBook:
    book = OrderBook("TEST")
    book.update("BUY", 0.49, 100)
    book.update("SELL", 0.51, 120)
    return book


def test_quality_monitor_degraded_and_halt_states():
    monitor = ExecutionQualityMonitor(
        smoothing=0.5,
        warn_slippage=0.01,
        halt_slippage=0.05,
        warn_latency_ms=200,
        halt_latency_ms=500,
        min_win_rate=0.6,
        halt_loss_streak=2,
    )

    monitor.record_fill("T1", pnl=-1.0, latency_ms=250, slippage=0.02)
    degraded = monitor.evaluate("T1")
    assert degraded.status == "degraded"
    assert math.isclose(degraded.size_multiplier, 0.7)
    assert degraded.spread_penalty > 0.0

    monitor.record_fill("T1", pnl=-0.5, latency_ms=600, slippage=0.06)
    halted = monitor.evaluate("T1")
    assert halted.status == "halt"
    assert halted.reason
    assert halted.size_multiplier == 0.0


def test_degraded_health_widens_quotes_and_scales_size():
    monitor = ExecutionQualityMonitor(warn_slippage=0.001, halt_slippage=1.0, min_win_rate=0.99)
    maker = SimpleMarketMaker(
        ["TEST"],
        dry_run=True,
        performance_tuner=None,
        execution_monitor=monitor,
    )
    book = build_basic_book()
    metrics = maker.compute_book_metrics("TEST", book)

    monitor.record_fill("TEST", pnl=-1.0, latency_ms=10, slippage=0.1)
    quote = maker._generate_quote_prices("TEST", metrics["mid"], book, metrics)
    assert quote is not None
    bid, ask = quote
    assert bid < 0.49  # widened bid due to spread penalty

    maker.execution_health["TEST"].size_multiplier = 0.5
    maker.quote_adjustments["TEST"].size_multiplier = 1.0
    maker.size = 10.0
    health_size_quote = maker.size * maker.quote_adjustments["TEST"].size_multiplier * maker.execution_health["TEST"].size_multiplier
    assert math.isclose(health_size_quote, 5.0)
