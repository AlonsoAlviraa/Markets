import csv
import os
from datetime import datetime
from typing import Dict, Optional

from src.core.paper_metrics import PaperMetricsExporter

class PaperTrader:
    """
    Paper trading simulator with realistic slippage and fees.
    Tracks virtual balance and logs all trades to CSV.
    """
    
    def __init__(
        self,
        initial_capital: float = 500.0,
        metrics_exporter: Optional[PaperMetricsExporter] = None,
    ):
        self.initial_capital = initial_capital
        self.virtual_balance = initial_capital
        self.trades_executed = 0
        self.total_profit = 0.0
        self.total_loss = 0.0
        self.log_file = os.getenv("PAPER_LOG_FILE", "simulation_results.csv")
        self.metrics_exporter = metrics_exporter or PaperMetricsExporter()
        
        # Trading costs (realistic estimates)
        self.polymarket_fee = 0.02  # 2% on profits
        self.sx_bet_fee = 0.02      # ~2% estimate
        self.slippage = 0.01        # 1% slippage per leg
        
        # Initialize CSV if doesn't exist
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Timestamp", "Event", "Strategy", "Position_Size",
                    "Expected_Profit", "Actual_Profit_After_Costs",
                    "Virtual_Balance", "ROI_Percent"
                ])
        
        print(f"📝 Paper Trader initialized")
        print(f"   Initial capital: ${self.initial_capital:.2f}")
        print(f"   Slippage: {self.slippage*100:.1f}% per leg")
        print(f"   Fees: Poly={self.polymarket_fee*100:.0f}%, SX={self.sx_bet_fee*100:.0f}%")
    
    def simulate_trade(self, opportunity: Dict, position_size: float) -> Dict:
        """
        Simulate a trade with realistic slippage and fees.
        Returns simulation results.
        """
        expected_profit_pct = opportunity['profit_percent']
        expected_profit_abs = opportunity['profit_absolute'] * position_size
        
        # Apply PESSIMISTIC adjustments
        # 1. Slippage on both legs (1% each = 2% total)
        slippage_cost = position_size * (self.slippage * 2)
        
        # 2. Fees (2% on profits for both platforms)
        fee_cost = expected_profit_abs * (self.polymarket_fee + self.sx_bet_fee)
        
        # 3. Calculate actual profit
        actual_profit = expected_profit_abs - slippage_cost - fee_cost
        actual_profit_pct = (actual_profit / position_size) * 100
        
        # Update virtual balance
        self.virtual_balance += actual_profit
        self.trades_executed += 1
        
        if actual_profit > 0:
            self.total_profit += actual_profit
        else:
            self.total_loss += abs(actual_profit)
        
        # Log to CSV
        with open(self.log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                opportunity['poly_event']['title'][:60],
                opportunity['strategy']['name'],
                position_size,
                f"{expected_profit_abs:.2f}",
                f"{actual_profit:.2f}",
                f"{self.virtual_balance:.2f}",
                f"{actual_profit_pct:.2f}"
            ])
        
        result = {
            "expected_profit": expected_profit_abs,
            "actual_profit": actual_profit,
            "slippage_cost": slippage_cost,
            "fee_cost": fee_cost,
            "new_balance": self.virtual_balance,
            "roi_percent": actual_profit_pct
        }
        
        # Print detailed breakdown
        print(f"\n  📝 PAPER TRADE SIMULATION:")
        print(f"     Expected profit: ${expected_profit_abs:.2f} ({expected_profit_pct:.2f}%)")
        print(f"     - Slippage: -${slippage_cost:.2f}")
        print(f"     - Fees: -${fee_cost:.2f}")
        print(f"     = Actual profit: ${actual_profit:.2f} ({actual_profit_pct:.2f}%)")
        print(f"     New balance: ${self.virtual_balance:.2f}")
        
        return result
    
    def get_stats(self) -> Dict:
        """Get current paper trading statistics"""
        total_return = self.virtual_balance - self.initial_capital
        roi_total = (total_return / self.initial_capital) * 100
        
        win_rate = 0.0
        if self.trades_executed > 0:
            winning_trades = self.trades_executed - (self.total_loss / abs(total_return) if total_return != 0 else 0)
            win_rate = (winning_trades / self.trades_executed) * 100
        
        return {
            "initial_capital": self.initial_capital,
            "current_balance": self.virtual_balance,
            "total_return": total_return,
            "roi_percent": roi_total,
            "trades_executed": self.trades_executed,
            "total_profit": self.total_profit,
            "total_loss": self.total_loss,
            "win_rate": win_rate
        }
    
    def print_summary(self):
        """Print paper trading summary"""
        stats = self.get_stats()
        
        print(f"\n{'='*60}")
        print(f"📊 PAPER TRADING SUMMARY")
        print(f"{'='*60}")
        print(f"Initial Capital:    ${stats['initial_capital']:.2f}")
        print(f"Current Balance:    ${stats['current_balance']:.2f}")
        print(f"Total Return:       ${stats['total_return']:.2f}")
        print(f"ROI:                {stats['roi_percent']:.2f}%")
        print(f"Trades Executed:    {stats['trades_executed']}")
        print(f"Total Profit:       ${stats['total_profit']:.2f}")
        print(f"Total Loss:         ${stats['total_loss']:.2f}")
        print(f"{'='*60}\n")

    def export_metrics_snapshot(self, positions: Optional[list] = None, filename: Optional[str] = None) -> str:
        """Persist a snapshot of paper metrics and positions for monitoring."""

        return self.metrics_exporter.export(
            stats=self.get_stats(),
            positions=positions or [],
            filename=filename,
        )

if __name__ == "__main__":
    # Test paper trader
    trader = PaperTrader(initial_capital=500)
    
    # Simulate a trade
    fake_opp = {
        'poly_event': {'title': 'Test Event'},
        'strategy': {'name': 'Test Strategy'},
        'profit_percent': 5.0,
        'profit_absolute': 0.05
    }
    
    trader.simulate_trade(fake_opp, position_size=100)
    trader.print_summary()
