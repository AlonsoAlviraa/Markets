import os
import sys

import asyncio
from datetime import datetime, timedelta

import pytest

sys.path.append(os.path.abspath("."))

from src.core.orderbook import OrderBook
from src.core.performance import AdaptiveQuoteController
from src.strategies.market_maker import SignalEnsembler, SimpleMarketMaker


def build_book(bids, asks):
    book = OrderBook("T")
    for price, size in bids.items():
        book.update("BUY", price, size)
    for price, size in asks.items():
        book.update("SELL", price, size)
    return book


@pytest.mark.parametrize(
    "bids,asks,mid,spread,imbalance,wide",
    [
        ({0.48: 100}, {0.52: 100}, 0.5, 0.04, 0.0, True),
        ({0.45: 50, 0.44: 30}, {0.55: 70}, 0.5, 0.1, pytest.approx(0.0667, rel=1e-3), True),
        ({0.4: 25}, {0.6: 25}, 0.5, 0.2, 0.0, True),
        ({0.6: 40}, {0.62: 80}, 0.61, 0.02, pytest.approx(-0.3333, rel=1e-3), False),
        ({0.3: 10, 0.28: 5}, {0.7: 20}, 0.5, 0.4, pytest.approx(-0.1429, rel=1e-3), True),
        ({0.48: 5}, {0.5: 5}, 0.49, 0.02, 0.0, False),
        ({0.2: 100, 0.19: 100}, {0.8: 20}, 0.5, 0.6, pytest.approx(0.8182, rel=1e-3), True),
        ({0.47: 80, 0.46: 20}, {0.53: 60, 0.54: 10}, 0.5, 0.06, pytest.approx(0.1765, rel=1e-3), True),
        ({0.51: 30}, {0.52: 70}, 0.515, 0.01, pytest.approx(-0.4, rel=1e-2), False),
        ({0.35: 40, 0.36: 10}, {0.65: 5, 0.66: 5}, 0.505, 0.29, pytest.approx(0.6667, rel=1e-3), True),
    ],
)
def test_compute_book_metrics_varied_books(bids, asks, mid, spread, imbalance, wide):
    maker = SimpleMarketMaker(["T"], dry_run=True)
    book = build_book(bids, asks)
    maker.books["T"] = book

    metrics = maker.compute_book_metrics("T", book)

    assert metrics["mid"] == pytest.approx(mid)
    assert metrics["spread"] == pytest.approx(spread)
    assert metrics["imbalance"] == pytest.approx(imbalance)
    assert metrics["wide_spread"] is wide


@pytest.mark.parametrize(
    "bids,asks,expected_bid,expected_ask",
    [
        ({0.48: 50}, {0.52: 50}, 0.49, 0.51),
        ({0.45: 100}, {0.55: 100}, 0.49, 0.51),
        ({0.4: 10}, {0.6: 10}, 0.49, 0.51),
        ({0.6: 10}, {0.62: 10}, 0.6, 0.62),
        ({0.2: 100}, {0.8: 20}, 0.489, 0.509),
        ({0.47: 80, 0.46: 10}, {0.53: 60, 0.54: 10}, 0.49, 0.51),
        ({0.51: 30}, {0.52: 70}, 0.505, 0.525),
        ({0.35: 40, 0.36: 10}, {0.65: 5, 0.66: 5}, 0.494, 0.514),
        ({0.55: 10}, {0.57: 10}, 0.55, 0.57),
        ({0.25: 100}, {0.75: 50}, 0.49, 0.51),
    ],
)
def test_generate_quote_prices_respects_buffers(bids, asks, expected_bid, expected_ask):
    maker = SimpleMarketMaker(["T"], dry_run=True, spread=0.02, inside_spread_ratio=0.5, inventory_skew=0.1)
    book = build_book(bids, asks)
    maker.books["T"] = book

    mid = book.get_mid_price()
    quote = maker._generate_quote_prices("T", mid, book)

    assert quote is not None
    bid, ask = quote
    assert bid == pytest.approx(expected_bid, rel=1e-3)
    assert ask == pytest.approx(expected_ask, rel=1e-3)
    assert bid < mid < ask


@pytest.mark.parametrize(
    "bids,asks,threshold,expected_tokens,top_mechanic",
    [
        ({0.48: 100}, {0.52: 20}, 0.4, 1, "inside-spread capture"),
        ({0.45: 50, 0.44: 30}, {0.55: 70}, 0.5, 1, "inside-spread capture"),
        ({0.4: 25}, {0.6: 25}, 0.5, 1, "inside-spread capture"),
        ({0.6: 40}, {0.62: 80}, 0.5, 1, "inventory skew"),
        ({0.2: 100, 0.19: 100}, {0.8: 20}, 0.5, 1, "inventory skew"),
        ({0.47: 80, 0.46: 20}, {0.53: 60, 0.54: 10}, 0.5, 1, "inside-spread capture"),
        ({0.51: 30}, {0.52: 70}, 0.5, 0, None),
        ({0.35: 40, 0.36: 10}, {0.65: 5, 0.66: 5}, 0.45, 1, "inventory skew"),
        ({0.55: 10}, {0.57: 10}, 0.5, 1, "steady alpha harvesting"),
        ({0.25: 100}, {0.75: 50}, 0.5, 1, "inventory skew"),
    ],
)
def test_find_opportunities_ranks_mechanics(bids, asks, threshold, expected_tokens, top_mechanic):
    maker = SimpleMarketMaker(["T"], dry_run=True, spread=0.02, opportunity_score_threshold=threshold)
    book = build_book(bids, asks)
    maker.books["T"] = book

    opportunities = maker.find_opportunities()

    assert len(opportunities) == expected_tokens
    if expected_tokens:
        assert top_mechanic in opportunities[0]["mechanics"]


def test_compute_book_metrics_tracks_volatility_and_vacuum():
    maker = SimpleMarketMaker(["T"], dry_run=True, spread=0.02, volatility_threshold=0.005)
    history_prices = [0.48, 0.49, 0.5, 0.505, 0.51]
    for price in history_prices:
        maker._record_mid("T", price)

    bids = {0.49: 1, 0.48: 9}
    asks = {0.51: 1, 0.52: 9}
    book = build_book(bids, asks)
    maker.books["T"] = book

    metrics = maker.compute_book_metrics("T", book)

    assert metrics["volatility"] > 0
    assert metrics["liquidity_vacuum"] is True
    assert metrics["top_depth_share"] == pytest.approx(0.1, rel=1e-3)


def test_find_opportunities_adds_new_mechanics():
    maker = SimpleMarketMaker(
        ["T"],
        dry_run=True,
        spread=0.02,
        volatility_threshold=0.005,
        trend_threshold=0.002,
        opportunity_score_threshold=0.3,
    )
    for price in [0.5, 0.505, 0.51, 0.512, 0.515]:
        maker._record_mid("T", price)

    book = build_book({0.49: 2}, {0.51: 2})
    maker.books["T"] = book

    opportunities = maker.find_opportunities()

    assert len(opportunities) == 1
    mechanics = opportunities[0]["mechanics"]
    assert "volatility breakout capture" in mechanics
    assert "trend leaning" in mechanics


@pytest.mark.parametrize(
    "prices,vol_mult,trend_mult,should_pause",
    [
        ([0.5, 0.56, 0.48, 0.6, 0.65], 1.0, 1.0, True),  # both extreme
        ([0.5, 0.56, 0.58, 0.59], 1.0, 10.0, True),  # volatility-only pause
        ([0.5, 0.505, 0.51, 0.52], 10.0, 1.0, True),  # trend-only pause
        ([0.5, 0.501, 0.502, 0.503], 10.0, 10.0, False),  # no pause
    ],
)
def test_generate_quote_prices_pauses_on_extreme_conditions(prices, vol_mult, trend_mult, should_pause):
    maker = SimpleMarketMaker(
        ["T"],
        dry_run=True,
        spread=0.02,
        volatility_threshold=0.005,
        trend_threshold=0.005,
        risk_pause_vol_multiplier=vol_mult,
        risk_pause_trend_multiplier=trend_mult,
    )
    for price in prices:
        maker._record_mid("T", price)

    bid_price = prices[-1]
    ask_price = bid_price + 0.02
    book = build_book({bid_price: 10}, {ask_price: 10})
    maker.books["T"] = book

    quote = maker._generate_quote_prices("T", book.get_mid_price(), book)

    if should_pause:
        assert quote is None
    else:
        assert quote is not None


def test_generate_quote_prices_widens_with_volatility():
    maker = SimpleMarketMaker(
        ["T"],
        dry_run=True,
        spread=0.02,
        inside_spread_ratio=0.5,
        volatility_threshold=0.001,
        risk_pause_vol_multiplier=100.0,
        risk_pause_trend_multiplier=100.0,
        trend_threshold=0.05,
    )
    for price in [0.5, 0.56, 0.48, 0.6]:
        maker._record_mid("T", price)

    book = build_book({0.51: 20}, {0.53: 20})
    maker.books["T"] = book

    quote = maker._generate_quote_prices("T", book.get_mid_price(), book)

    assert quote is not None
    bid, ask = quote
    assert (ask - bid) > 0.02


def test_social_signals_adjust_quotes_and_scoring():
    base_maker = SimpleMarketMaker(["T"], dry_run=True, spread=0.02, inside_spread_ratio=0.5)
    social_maker = SimpleMarketMaker(
        ["T"],
        dry_run=True,
        spread=0.02,
        inside_spread_ratio=0.5,
        social_sentiment_bias=0.6,
        whale_pressure_widen=0.3,
        opportunity_score_threshold=0.2,
    )

    bids = {0.49: 20}
    asks = {0.51: 20}
    base_book = build_book(bids, asks)
    social_book = build_book(bids, asks)
    base_maker.books["T"] = base_book
    social_maker.books["T"] = social_book

    social_maker.ingest_social_signal("T", sentiment=0.7, buzz=0.8, whale_pressure=0.6)

    base_quote = base_maker._generate_quote_prices("T", base_book.get_mid_price(), base_book)
    social_quote = social_maker._generate_quote_prices(
        "T", social_book.get_mid_price(), social_book
    )

    assert base_quote is not None and social_quote is not None
    base_bid, base_ask = base_quote
    social_bid, social_ask = social_quote

    # Positive sentiment should keep us leaning upward, while buzz/whales widen spreads
    assert social_bid >= base_bid
    assert social_ask > base_ask
    assert (social_ask - social_bid) > (base_ask - base_bid)

    opportunities = social_maker.find_opportunities()
    assert opportunities
    mechanics = opportunities[0]["mechanics"]
    assert "social buzz momentum" in mechanics
    assert "whale shadowing" in mechanics


def test_signal_ensembler_learns_from_labels():
    model = SignalEnsembler()
    bullish_features = {
        "spread": 0.12,
        "imbalance": 0.4,
        "volatility": 0.02,
        "micro_trend": 0.01,
        "liquidity_vacuum": 1.0,
        "whale_pressure": 0.7,
        "social_buzz": 0.6,
        "whale_shadow_bias": 0.4,
    }
    base_pred = model.predict(bullish_features)

    samples = (
        [{"features": bullish_features, "label": 1.0}] * 6
        + [
            {
                "features": {
                    **bullish_features,
                    "whale_pressure": 0.0,
                    "spread": 0.01,
                    "liquidity_vacuum": 0.0,
                },
                "label": 0.0,
            }
        ]
        * 6
    )
    model.fit(samples)

    assert model.ready is True
    assert model.predict(bullish_features) > base_pred


def test_stale_book_pauses_quotes():
    maker = SimpleMarketMaker(["T"], dry_run=True, stale_quote_seconds=0.0)
    book = build_book({0.49: 10}, {0.51: 10})
    maker.books["T"] = book

    maker.last_book_update["T"] = datetime.utcnow() - timedelta(seconds=5)
    quote = maker._generate_quote_prices("T", book.get_mid_price(), book)
    assert quote is None


def test_whale_shadowing_feeds_ml_mechanics():
    base_maker = SimpleMarketMaker(["T"], dry_run=True, spread=0.02, inside_spread_ratio=0.5, ml_edge_weight=0.25)
    whale_maker = SimpleMarketMaker(
        ["T"],
        dry_run=True,
        spread=0.02,
        inside_spread_ratio=0.5,
        ml_edge_weight=0.5,
        opportunity_score_threshold=0.2,
    )

    bids = {0.4: 50}
    asks = {0.6: 50}
    base_book = build_book(bids, asks)
    whale_book = build_book(bids, asks)
    base_maker.books["T"] = base_book
    whale_maker.books["T"] = whale_book

    whale_maker.record_whale_action("T", "BUY", size=50, confidence=0.9)
    whale_metrics = whale_maker.compute_book_metrics("T", whale_book)

    base_quote = base_maker._generate_quote_prices("T", base_book.get_mid_price(), base_book)
    whale_quote = whale_maker._generate_quote_prices("T", whale_book.get_mid_price(), whale_book)

    assert base_quote and whale_quote
    assert whale_quote[0] > base_quote[0]
    assert whale_metrics["whale_shadow_bias"] > 0

    training_example = {
        "features": {
            "spread": whale_metrics["spread"],
            "imbalance": whale_metrics["imbalance"],
            "volatility": whale_metrics["volatility"],
            "micro_trend": whale_metrics["micro_trend"],
            "liquidity_vacuum": 1.0 if whale_metrics["liquidity_vacuum"] else 0.0,
            "whale_pressure": whale_metrics["whale_pressure"],
            "social_buzz": whale_metrics["social_buzz"],
            "whale_shadow_bias": whale_metrics["whale_shadow_bias"],
        },
        "label": 1.0,
    }
    whale_maker.train_signal_model([training_example] * 6)

    opportunities = whale_maker.find_opportunities()
    assert opportunities
    mechanics = opportunities[0]["mechanics"]
    assert "alpha wallet shadow" in mechanics
    assert "ml edge confirmation" in mechanics


def test_regime_detection_widens_and_tags_mechanics():
    quiet_maker = SimpleMarketMaker(["T"], dry_run=True, spread=0.02, regime_spread_widen=0.2)
    regime_maker = SimpleMarketMaker(
        ["T"],
        dry_run=True,
        spread=0.02,
        regime_spread_widen=0.3,
        opportunity_score_threshold=0.2,
        risk_pause_vol_multiplier=10.0,
        risk_pause_trend_multiplier=10.0,
    )

    bids = {0.49: 30}
    asks = {0.51: 30}
    quiet_book = build_book(bids, asks)
    regime_book = build_book(bids, asks)
    quiet_maker.books["T"] = quiet_book
    regime_maker.books["T"] = regime_book

    for price in [0.49, 0.5, 0.52, 0.55]:
        regime_maker._record_mid("T", price)
    regime_maker.ingest_social_signal("T", sentiment=0.6, buzz=0.8, whale_pressure=0.7)
    regime_maker.record_whale_action("T", "BUY", size=80, confidence=0.9)

    quiet_quote = quiet_maker._generate_quote_prices("T", quiet_book.get_mid_price(), quiet_book)
    regime_quote = regime_maker._generate_quote_prices("T", regime_book.get_mid_price(), regime_book)

    assert quiet_quote and regime_quote
    quiet_spread = quiet_quote[1] - quiet_quote[0]
    regime_spread = regime_quote[1] - regime_quote[0]
    assert regime_spread > quiet_spread

    opportunities = regime_maker.find_opportunities()
    assert opportunities
    mechanics = opportunities[0]["mechanics"]
    assert "whale burst chase" in mechanics
    assert any(tag in mechanics for tag in ["buzz echo capture", "social buzz momentum"])


def test_ml_score_gated_until_confident():
    model = SignalEnsembler(min_fit_samples=4)
    maker = SimpleMarketMaker(
        ["T"],
        dry_run=True,
        spread=0.02,
        inside_spread_ratio=0.5,
        ml_edge_weight=0.6,
        ml_confidence_floor=0.1,
        signal_model=model,
        opportunity_score_threshold=0.1,
    )

    book = build_book({0.48: 20}, {0.52: 20})
    maker.books["T"] = book
    baseline_metrics = maker.compute_book_metrics("T", book)

    low_conf_score = maker._score_opportunity(baseline_metrics)

    sample = {
        "features": maker._build_ml_features(baseline_metrics),
        "label": 1.0,
    }
    maker.train_signal_model([sample] * 6)

    trained_score = maker._score_opportunity(baseline_metrics)

    assert trained_score > low_conf_score


class _CaptureExecutor:
    def __init__(self):
        self.placed = []

    def cancel_order(self, order_id):
        return order_id

    def place_order(self, token_id, side, price, size):
        self.placed.append({"token": token_id, "side": side, "price": price, "size": size})
        return f"{token_id}-{side}"


def test_adaptive_tuner_scales_quote_size_and_spread():
    tuner = AdaptiveQuoteController(target_fill_rate=0.4, volatility_threshold=0.002)
    executor = _CaptureExecutor()
    maker = SimpleMarketMaker(
        ["T"],
        executor=executor,
        dry_run=False,
        spread=0.02,
        performance_tuner=tuner,
        volatility_threshold=0.002,
        risk_pause_vol_multiplier=10.0,
        risk_pause_trend_multiplier=10.0,
    )

    # Strong fills should increase size and tighten spreads slightly
    for _ in range(4):
        tuner.record_fill("T", filled=True, latency_ms=60, slippage=0.0)

    book = build_book({0.49: 20}, {0.51: 20})
    maker.books["T"] = book

    asyncio.run(maker.update_quotes("T", book.get_mid_price(), book))

    assert executor.placed, "Orders should be placed with live executor"
    sizes = {o["size"] for o in executor.placed}
    assert all(size >= maker.size for size in sizes)
    assert any(size > maker.size for size in sizes)


