import itertools
import logging
from typing import Callable, Dict, Iterable, List, Tuple

logger = logging.getLogger(__name__)


class ThresholdGridRunner:
    """Runs a grid search over ML edge and whale-pressure thresholds.

    The runner is lightweight and delegates evaluation to a user-provided
    callback so it can be reused in paper, backtests, or live shadow-mode.
    """

    def __init__(
        self,
        ml_edges: Iterable[float],
        whale_pressures: Iterable[float],
        evaluator: Callable[[float, float], Dict],
    ) -> None:
        self.ml_edges = list(ml_edges)
        self.whale_pressures = list(whale_pressures)
        self.evaluator = evaluator

    def run(self) -> List[Tuple[float, float, Dict]]:
        """Execute the grid search and return scored combinations."""

        results: List[Tuple[float, float, Dict]] = []
        for ml_edge, whale_pressure in itertools.product(self.ml_edges, self.whale_pressures):
            try:
                metrics = self.evaluator(ml_edge, whale_pressure)
                metrics["ml_edge"] = ml_edge
                metrics["whale_pressure"] = whale_pressure
                results.append((ml_edge, whale_pressure, metrics))
                logger.info(
                    "[GRID] ML Edge=%.2f Whale Pressure=%.2f | metrics=%s",
                    ml_edge,
                    whale_pressure,
                    metrics,
                )
            except Exception as exc:  # pragma: no cover - operational guard
                logger.exception("[GRID] Failed at ml_edge=%s whale=%s", ml_edge, whale_pressure)

        # Sort by best PnL / drawdown combo if available
        results.sort(
            key=lambda x: (
                -float(x[2].get("pnl", 0.0)),
                float(x[2].get("drawdown", 1.0)),
            )
        )
        return results

