# 📝 Paper Trading Guide - Zero Risk Validation

## ¿Qué es Paper Trading?

**Simulación 100% realista sin gastar $1**. El bot opera normalmente pero NO envía transacciones a blockchain. En su lugar:
- Registra cada trade en CSV
- Simula slippage (1% por leg)
- Simula fees (2% Poly + 2% SX)
- Trackea balance virtual

## 🎯 Por Qué Es Crítico

**NUNCA** vayas a LIVE sin paper trading porque:
1. Validas frecuencia de oportunidades (¿0/día o 10/día?)
2. Detectas bugs en lógica SIN perder dinero
3. Calculas ROI realista (con fees y slippage)
4. Identificas false positives en matching

## 🚀 Setup (2 minutos)

```bash
# 1. Configurar .env
echo "MODE=PAPER_TRADING" >> .env
echo "INITIAL_VIRTUAL_CAPITAL=500" >> .env
echo "PAPER_LOG_FILE=simulation_results.csv" >> .env

# 2. Ejecutar bot
python automated_bot.py

# Verás en logs:
# "📝 Paper Trader initialized"
# "📝 PAPER TRADE SIMULATION"
```

## 📊 New Dashboard (Premium)

Now you can visualize your paper trading performance with the new Premium Dashboard:

```bash
# 1. Run simulation
python scripts/simulate_paper_session.py

# 2. Generate Dashboard
python src/utils/dashboard_generator.py

# 3. Open 'data/paper_metrics/dashboard.html' in your browser
```

The dashboard includes:
- 📈 **Equity Curve**: Visualize your PnL over time.
- 📉 **Drawdown Tracker**: Monitor max usage of your capital.
- 🚨 **Canary Blocks**: See where the circuit breakers triggered.


## ✅ Validación Checklist

Después de 24-48h de paper trading, verifica:

- [ ] **Frecuencia**: Min 2-5 trades/día _(si 0 → bajar MIN_PROFIT_PERCENT)_
- [ ] **Win Rate**: >70% _(si <50% → revisar matching logic)_
- [ ] **ROI After Costs**: >20% _(si <0% → estrategia no funciona)_
- [ ] **False Positives**: Revisar CSV, ¿hay Man City vs Man United? _(si sí → subir fuzzy threshold)_

## 🚨 Red Flags

**DETÉN y revisa si:**
- ❌ ROI < 0% después de 100 trades
- ❌ Win rate < 40%
- ❌ Muchos "Manchester City" vs "Manchester United" en logs
- ❌ Profit esperado muy distinto de profit real (slippage >5%)

## 📈 Cuándo Ir a LIVE

Solo pasa a LIVE cuando:
1. ✅ Paper trading 48h con ROI > 20%
2. ✅ Win rate > 70%
3. ✅ Frecuencia estable (3+ trades/día)
4. ✅ Zero false positives en últimas 50 trades

## 🎓 Limitaciones del Paper Trading

**Lo que SÍ simula:**
- Slippage (1% por leg)
- Fees (4% total)
- Matching logic
- Frecuencia de oportunidades

**Lo que NO simula:**
- Network congestion (transacciones fallidas)
- Liquidez real (asume órdenes se llenan)
- Nonce errors
- Bridge delays

**Solución**: Primero paper → luego LIVE con $10 posiciones.

## 📋 Workflow Completo

```bash
# FASE 1: Paper Trading (48h)
MODE=PAPER_TRADING python automated_bot.py
python analyze_simulation.py

# FASE 2: Micro Live ($10 positions, 24h)
MODE=LIVE MAX_POSITION_SIZE=10 python automated_bot.py

# FASE 3: Escalar ($50/$100)
MAX_POSITION_SIZE=50 python automated_bot.py
```

## 💡 Tips

1. **Corre 48-72h** (no solo 6h) para capturar ciclos de mercado
2. **Analiza daily** con `analyze_simulation.py`
3. **Compara expected vs actual profit** - si muy diferente, ajusta fees
4. **Weekend vs Weekday** - puede haber diferencias
5. **Guarda CSVs** para comparar versiones del bot

---

**Paper trading es GRATIS y te puede ahorrar $500 en bugs** 🎯
