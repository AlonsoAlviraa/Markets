import csv
import os
import sys
import asyncio
import csv
import os
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.append(os.path.abspath("."))

from src.core.paper_metrics import PaperMetricsExporter
from src.core.paper_trader import PaperTrader
from src.core.risk import CanaryGuard, DrawdownGuard
from src.strategies.market_maker import SimpleMarketMaker
from src.core.orderbook import OrderBook


def test_canary_guard_blocks_live_quotes():
    guard = CanaryGuard(per_token_notional=4.0, daily_notional_limit=6.0, max_consecutive_losses=1)
    maker = SimpleMarketMaker(
        ["T"],
        executor=object(),
        dry_run=False,
        size=10.0,
        canary_guard=guard,
    )
    maker.execute_quotes = AsyncMock()

    book = OrderBook("T")
    book.update("BUY", 0.49, 10)
    book.update("SELL", 0.51, 10)
    maker.books["T"] = book

    asyncio.run(maker.update_quotes("T", book.get_mid_price(), book))
    maker.execute_quotes.assert_not_called()

    guard.consecutive_losses = 2
    guard.max_consecutive_losses = 1
    assert guard.check_order("T", 1.0) == "consecutive_losses"


def test_paper_trader_exports_drawdowns(tmp_path):
    os.environ["PAPER_LOG_FILE"] = str(tmp_path / "paper_log.csv")
    exporter = PaperMetricsExporter(output_dir=str(tmp_path))
    trader = PaperTrader(initial_capital=100.0, metrics_exporter=exporter)

    trader.virtual_balance = 120.0
    first_path = trader.export_metrics_snapshot(
        positions=[{"token_id": "T", "position": 5, "trades": 2, "pnl": 10.0}],
        filename="snap1.csv",
    )

    trader.virtual_balance = 110.0
    second_path = trader.export_metrics_snapshot(
        positions=[{"token_id": "T", "position": 6, "trades": 3, "pnl": 8.0}],
        filename="snap2.csv",
    )

    assert os.path.exists(first_path)
    assert os.path.exists(second_path)

    with open(second_path, newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows, "Snapshot should contain rows"
    drawdown = float(rows[0]["drawdown"])
    assert drawdown > 0.0


def test_drawdown_guard_blocks_after_losses():
    guard = DrawdownGuard(starting_equity=1000.0, max_daily_loss=20.0, max_drawdown_pct=0.05)

    assert guard.register_fill(-5.0) is None
    assert guard.register_fill(-10.0) is None
    assert guard.register_fill(-7.0) == "daily_loss_limit"

    guard.current_equity = 950.0
    guard.peak_equity = 1000.0
    guard.daily_pnl = 0.0
    assert guard.check_equity(940.0) == "drawdown_limit"
