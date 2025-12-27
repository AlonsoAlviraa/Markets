import pytest

from src.core.performance import AdaptiveQuoteController


def test_adaptive_quote_controller_tightens_with_strong_fills():
    controller = AdaptiveQuoteController(target_fill_rate=0.5, slippage_threshold=0.02)

    for _ in range(5):
        controller.record_fill("T", filled=True, latency_ms=80, slippage=0.0)

    adjustment = controller.compute_adjustment("T", volatility=0.005, latency_ms=50)

    assert adjustment.size_multiplier > 1.0
    assert adjustment.spread_widen < 0


def test_adaptive_quote_controller_widens_on_latency_and_slippage():
    controller = AdaptiveQuoteController(volatility_threshold=0.002, latency_threshold_ms=100)

    controller.record_fill("T", filled=False, latency_ms=250, slippage=0.03)
    controller.record_fill("T", filled=False, latency_ms=200, slippage=0.025)

    adjustment = controller.compute_adjustment("T", volatility=0.01, latency_ms=250)

    assert adjustment.spread_widen > 0
    assert adjustment.size_multiplier < 1.0
