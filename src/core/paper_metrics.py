import csv
import os
from datetime import datetime
from typing import Dict, List, Optional


class PaperMetricsExporter:
    """Exports paper-trading snapshots for monitoring and validation.

    The exporter tracks daily equity so it can compute simple drawdowns and
    write structured CSV snapshots to `/data/paper_metrics/` by default.
    """

    def __init__(self, output_dir: str = "data/paper_metrics") -> None:
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.equity_curve: List[float] = []

    def _compute_drawdown(self, equity: float) -> float:
        if not self.equity_curve:
            return 0.0
        peak = max(self.equity_curve)
        if peak == 0:
            return 0.0
        return round((peak - equity) / peak, 4)

    def export(
        self,
        *,
        stats: Dict,
        positions: Optional[List[Dict]] = None,
        filename: Optional[str] = None,
    ) -> str:
        """Write a daily CSV snapshot with PnL, drawdown, and positions.

        Args:
            stats: Output of PaperTrader.get_stats() or compatible dict.
            positions: Optional list of per-token metrics `{token_id, position, trades, pnl}`.
            filename: Optional file name override.
        Returns:
            Path to the created CSV file.
        """

        positions = positions or []
        equity = float(stats.get("current_balance", 0.0))
        self.equity_curve.append(equity)
        drawdown = self._compute_drawdown(equity)

        today = datetime.utcnow().strftime("%Y%m%d")
        fname = filename or f"paper_metrics_{today}.csv"
        fpath = os.path.join(self.output_dir, fname)

        fieldnames = [
            "timestamp",
            "token_id",
            "position",
            "trades",
            "pnl_virtual",
            "drawdown",
            "total_trades",
            "total_profit",
            "total_loss",
            "unrealized_equity",
        ]

        with open(fpath, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()

            for pos in positions or [{"token_id": "ALL"}]:
                writer.writerow(
                    {
                        "timestamp": datetime.utcnow().isoformat(),
                        "token_id": pos.get("token_id", "ALL"),
                        "position": pos.get("position", 0.0),
                        "trades": pos.get("trades", 0),
                        "pnl_virtual": pos.get("pnl", 0.0),
                        "drawdown": drawdown,
                        "total_trades": stats.get("trades_executed", 0),
                        "total_profit": stats.get("total_profit", 0.0),
                        "total_loss": stats.get("total_loss", 0.0),
                        "unrealized_equity": stats.get("current_balance", 0.0),
                    }
                )

        return fpath

