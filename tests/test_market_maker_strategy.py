import os
import sys

import pytest

sys.path.append(os.path.abspath("."))

from src.core.orderbook import OrderBook
from src.strategies.market_maker import SimpleMarketMaker


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


