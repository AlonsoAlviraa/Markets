import csv
import glob
import json
import os
from datetime import datetime
from typing import Dict, List

def load_metrics(data_dir: str) -> List[Dict]:
    """Load and aggregate all CSV metrics from the data directory."""
    files = glob.glob(os.path.join(data_dir, "paper_metrics_*.csv"))
    all_data = []
    
    for fpath in sorted(files):
        with open(fpath, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert types
                try:
                    row["timestamp"] = row["timestamp"]
                    row["pnl_virtual"] = float(row.get("pnl_virtual", 0.0))
                    row["drawdown"] = float(row.get("drawdown", 0.0))
                    row["unrealized_equity"] = float(row.get("unrealized_equity", 0.0))
                    all_data.append(row)
                except ValueError:
                    continue
    
    # Sort by timestamp
    all_data.sort(key=lambda x: x["timestamp"])
    return all_data

def generate_html(data: List[Dict], output_path: str):
    """Generate a premium HTML dashboard with Chart.js."""
    
    # Prepare data for charts
    timestamps = [d["timestamp"] for d in data if d["token_id"] == "ALL"]
    equity = [d["unrealized_equity"] for d in data if d["token_id"] == "ALL"]
    drawdowns = [d["drawdown"] * 100 for d in data if d["token_id"] == "ALL"]
    
    # KPIs
    current_equity = equity[-1] if equity else 1000.0
    max_dd = max(drawdowns) if drawdowns else 0.0
    total_trades = data[-1]["total_trades"] if data else 0
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Antigravity Market Maker | Paper Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            :root {{
                --bg-primary: #0f172a;
                --bg-secondary: #1e293b;
                --text-primary: #f8fafc;
                --text-secondary: #94a3b8;
                --accent: #38bdf8;
                --success: #4ade80;
                --danger: #f87171;
            }}
            body {{
                font-family: 'Inter', system-ui, -apple-system, sans-serif;
                background-color: var(--bg-primary);
                color: var(--text-primary);
                margin: 0;
                padding: 2rem;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            header {{
                margin-bottom: 2rem;
                border-bottom: 1px solid var(--bg-secondary);
                padding-bottom: 1rem;
            }}
            h1 {{ font-weight: 700; letter-spacing: -0.025em; margin: 0; }}
            .subtitle {{ color: var(--text-secondary); margin-top: 0.5rem; }}
            
            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 1.5rem;
                margin-bottom: 2rem;
            }}
            .card {{
                background: var(--bg-secondary);
                border-radius: 1rem;
                padding: 1.5rem;
                border: 1px solid rgba(255,255,255,0.05);
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            }}
            .kpi-label {{ color: var(--text-secondary); font-size: 0.875rem; font-weight: 500; }}
            .kpi-value {{ font-size: 2rem; font-weight: 700; margin-top: 0.5rem; }}
            .kpi-value.green {{ color: var(--success); }}
            .kpi-value.red {{ color: var(--danger); }}
            
            .chart-container {{
                position: relative;
                height: 400px;
                width: 100%;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>🚀 Paper Trading Performance</h1>
                <div class="subtitle">Live Metrics & Drawdown Monitoring</div>
            </header>
            
            <div class="grid">
                <div class="card">
                    <div class="kpi-label">Current Equity</div>
                    <div class="kpi-value text-gradient">${current_equity:,.2f}</div>
                </div>
                <div class="card">
                    <div class="kpi-label">Max Drawdown</div>
                    <div class="kpi-value red">{max_dd:.2f}%</div>
                </div>
                <div class="card">
                    <div class="kpi-label">Total Trades</div>
                    <div class="kpi-value">{total_trades}</div>
                </div>
            </div>
            
            <div class="card">
                <h3 style="margin-top:0">Equity Curve</h3>
                <div class="chart-container">
                    <canvas id="equityChart"></canvas>
                </div>
            </div>
        </div>

        <script>
            const ctx = document.getElementById('equityChart').getContext('2d');
            
            const gradient = ctx.createLinearGradient(0, 0, 0, 400);
            gradient.addColorStop(0, 'rgba(56, 189, 248, 0.5)');
            gradient.addColorStop(1, 'rgba(56, 189, 248, 0.0)');

            new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: {json.dumps(timestamps)},
                    datasets: [{{
                        label: 'Portfolio Equity ($)',
                        data: {json.dumps(equity)},
                        borderColor: '#38bdf8',
                        backgroundColor: gradient,
                        borderWidth: 2,
                        pointRadius: 0,
                        fill: true,
                        tension: 0.4
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: {{
                            mode: 'index',
                            intersect: false,
                            backgroundColor: '#1e293b',
                            titleColor: '#f8fafc',
                            bodyColor: '#94a3b8',
                            borderColor: 'rgba(255,255,255,0.1)',
                            borderWidth: 1
                        }}
                    }},
                    scales: {{
                        x: {{
                            display: false,
                            grid: {{ display: false }}
                        }},
                        y: {{
                            grid: {{ color: 'rgba(255,255,255,0.05)' }},
                            ticks: {{ color: '#94a3b8' }}
                        }}
                    }},
                    interaction: {{
                        mode: 'nearest',
                        axis: 'x',
                        intersect: false
                    }}
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[OK] Dashboard generated at: {output_path}")

if __name__ == "__main__":
    DATA_DIR = os.path.join("data", "paper_metrics")
    OUTPUT_FILE = os.path.join(DATA_DIR, "dashboard.html")
    
    print(f"Reading metrics from {DATA_DIR}...")
    if not os.path.exists(DATA_DIR):
        print(f"Creating directory {DATA_DIR}...")
        os.makedirs(DATA_DIR, exist_ok=True)
        # Create a dummy file for testing if none exists
        dummy_path = os.path.join(DATA_DIR, "paper_metrics_test.csv")
        with open(dummy_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "timestamp", "token_id", "position", "trades", "pnl_virtual", 
                "drawdown", "total_trades", "total_profit", "total_loss", "unrealized_equity"
            ])
            writer.writeheader()
            writer.writerow({
                "timestamp": datetime.utcnow().isoformat(),
                "token_id": "ALL",
                "position": 0, "trades": 0, "pnl_virtual": 0, "drawdown": 0,
                "total_trades": 0, "total_profit": 0, "total_loss": 0, "unrealized_equity": 1000.0
            })
    
    data = load_metrics(DATA_DIR)
    generate_html(data, OUTPUT_FILE)
