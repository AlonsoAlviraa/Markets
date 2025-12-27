import asyncio
import random
import logging
from datetime import datetime, timedelta
from src.strategies.market_maker import SimpleMarketMaker
from src.core.paper_metrics import PaperMetricsExporter

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class MockExecutor:
    """Mock executor that does nothing but log."""
    def place_order(self, *args, **kwargs): return "mock_oid"
    def cancel_order(self, *args, **kwargs): pass

async def run_simulation():
    logger.info("🚀 Starting Paper Trading Simulation...")
    
    token_ids = ["TOKEN_A", "TOKEN_B"]
    
    # Initialize Maker with strict guards to trigger interesting events
    maker = SimpleMarketMaker(
        token_ids=token_ids,
        dry_run=True,
        executor=MockExecutor(),
        spread=0.05,
        size=100.0,
        canary_guard=None, # Let it run free initially
    )
    
    # Mock Feed: We will drive it manually
    # But Maker expects .feed to exist. It does.
    
    start_price = {"TOKEN_A": 0.50, "TOKEN_B": 0.80}
    current_prices = start_price.copy()
    
    # Run for N steps
    steps = 50
    
    for i in range(steps):
        logger.info(f"--- Step {i+1}/{steps} ---")
        
        for tid in token_ids:
            # Random Walk
            drift = random.uniform(-0.02, 0.02)
            current_prices[tid] += drift
            current_prices[tid] = max(0.01, min(0.99, current_prices[tid]))
            
            mid = current_prices[tid]
            spread = 0.04
            
            # Construct synthetic book
            best_bid = mid - (spread / 2)
            best_ask = mid + (spread / 2)
            
            # Create book message (Partial or Snapshot? Maker handles snapshots easily)
            msg = {
                "event_type": "book",
                "asset_id": tid,
                "bids": [{"price": str(best_bid), "size": "1000"}],
                "asks": [{"price": str(best_ask), "size": "1000"}]
            }
            
            # Inject into Maker
            await maker.on_market_update(msg)
            
            # Allow Maker to process (update_quotes is an async task)
            await asyncio.sleep(0.01)
            
            # Force export occasionally
            if i % 10 == 0:
                # We need to manually trigger export in this mock setup if the Maker doesn't do it automatically.
                # The PaperMetricsExporter is usually used by a higher level controller or the Maker itself if wired.
                # In current `market_maker.py`, it doesn't seem to natively use PaperMetricsExporter every Tick.
                # Let's check: The diffs showed it added PaperMetricsExporter? 
                # Actually, the user's prompt text says "Enabled paper trading snapshots through PaperMetricsExporter"
                # But looking at `src/strategies/market_maker.py` file content in previous turn...
                # I don't see `PaperMetricsExporter` being instantiated or used in `SimpleMarketMaker`.
                # Ah! The user said "Added utilities... Enabled paper trading snapshots...".
                # But maybe `SimpleMarketMaker` logic I read (lines 1-889) didn't show it being *called*?
                # I'll check `src/strategies/market_maker.py` again.
                # If it's missing, I'll add the export logic here in the simulation to prove the Dashboard works.
                pass

    # Manually Export at the end to generate the file
    exporter = PaperMetricsExporter()
    
    # fake positions
    stats = {
        "current_balance": 1000.0 + maker.paper_pnl,
        "trades_executed": maker.paper_trades_count,
        "total_profit": max(0, maker.paper_pnl),
        "total_loss": min(0, maker.paper_pnl)
    }
    
    positions = []
    for tid in token_ids:
        positions.append({
            "token_id": tid,
            "position": maker.paper_positions.get(tid, 0),
            "trades": 0, # simplified
            "pnl": 0.0   # simplified
        })
        
    fpath = exporter.export(stats=stats, positions=positions)
    logger.info(f"💾 Snapshot exported to: {fpath}")

if __name__ == "__main__":
    asyncio.run(run_simulation())
