#!/bin/bash
# Run the new Market Maker with Risk Guardrails

# Set Python Path to include the current directory
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Run the Market Maker
# You can override parameters via flags if implemented in __main__ of market_maker.py
# For now, it runs the async loop.

echo "🚀 Starting Market Maker..."
echo "📊 Dashboard will be generated in data/paper_metrics/"

python src/strategies/market_maker.py
