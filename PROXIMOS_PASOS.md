# Próximos pasos para el Sistema de Trading Automatizado

Este documento detalla el plan inmediato para evolucionar del estado actual (paper trading) hacia una operación controlada en producción. Cada sección incluye objetivos, criterios de éxito y **pasos concretos a ejecutar** con responsables, datos de entrada y artefactos de salida.

## 1. Monitoreo y validación en paper trading
- **Objetivo:** Confirmar la solidez de los fills simulados y el PnL virtual.
- **Pasos a ejecutar (diario, horario UTC 23:00):**
  1. Exportar snapshot a CSV (`data/paper_metrics_YYYYMMDD.csv`) con: token, posición, trades, PnL virtual, drawdown máximo del día.
  2. Adjuntar el CSV en el canal interno y archivar en `/data/paper_metrics/`.
  3. Revisar manualmente 3 muestras aleatorias y validar que el PnL coincide con los logs de fills.
  4. Emitir alerta en Telegram cuando el PnL virtual diario cruce ±$150.
- **Criterio de éxito:** 7 días consecutivos con PnL virtual > $0 y drawdown intradía < 8%.

## 2. Ajuste de umbrales (ML Edge y Whale Pressure)
- **Objetivo:** Optimizar el balance entre frecuencia de operaciones y calidad de señal.
- **Pasos a ejecutar (semana 1, días 1-3):**
  1. Ejecutar grid con `ML Edge ∈ {0.65, 0.70, 0.75}` y `Whale Pressure ∈ {0.45, 0.50, 0.55}` en paper, 24h por combinación.
  2. Capturar métricas por combinación: ratio de fills, PnL virtual, slippage simulado, falsos positivos.
  3. Seleccionar combinación con mejor PnL vs drawdown y actualizar configuración por defecto.
- **Criterio de éxito:** +10% PnL virtual vs baseline sin aumento de falsos positivos > 3 p.p.

## 3. Checklist para activar LIVE trading
- **Objetivo:** Reducir riesgo al pasar de paper a live.
- **Pasos a ejecutar (semana 2, día 1):**
  1. Configurar límites duros por mercado: notional máx. $150 por token y $800 por día.
  2. Activar modo "canary" con tamaño mínimo (5% del notional estándar) y rollback automático tras 3 pérdidas consecutivas.
  3. Verificar segmentación de claves: credenciales live separadas de paper y con permisos mínimos.
- **Criterio de éxito:** Canary estable durante 3 días sin violar límites ni degradar PnL (< -$50).

## 4. Controles de riesgo y resiliencia
- **Objetivo:** Proteger contra eventos extremos y fallas operativas.
- **Pasos a ejecutar (semana 2, días 2-3):**
  1. Implementar circuit breaker por volatilidad: pausar quoting si volatilidad intradía > 2.0x media de 7d.
  2. Implementar circuit breaker por error rate: pausar si error de API > 5% en la última hora.
  3. Añadir watchdog de latencia: degradar a modo pasivo si feed > 250 ms durante 5 min.
  4. Registrar cada orden (paper/live) con ID trazable y checksum de snapshot.
- **Criterio de éxito:** Circuit breakers se activan en pruebas de estrés y el bot se recupera sin intervención manual.

## 5. Mejoras de modelo y señal
- **Objetivo:** Incrementar la calidad de las predicciones sin dependencias pesadas.
- **Pasos a ejecutar (semana 3, días 1-3):**
  1. Añadir features ligeros: skew de order book (nivel 1), tiempo desde último fill, ratio de bursts sociales.
  2. Ajustar decay dinámico: 0.93 en régimen "volatile", 0.97 en "drifting" y "social-buzz".
  3. Implementar ensamble con "confidence gating" que priorice presión de ballenas > 0.55.
- **Criterio de éxito:** +5 p.p. en tasa de acierto en backtests de paper con significancia estadística.

## 6. Observabilidad y alerting
- **Objetivo:** Tener visibilidad completa en tiempo real.
- **Pasos a ejecutar (semana 2, día 4):**
  1. Desplegar panel Grafana ligero con métricas: spreads, régimen detectado, presión de ballenas, edge ML, fills y PnL.
  2. Añadir health-checks cada 2 min para Polymarket y PolygonScan; publicar estado en Telegram.
  3. Consolidar logs estructurados JSON con nivel DEBUG opcional y retención de 14 días.
- **Criterio de éxito:** Panel actualizado en tiempo real y alertas recibidas en <1 min ante fallos.

## 7. Gobernanza operativa
- **Objetivo:** Alinear el despliegue con controles y revisiones claras.
- **Pasos a ejecutar (continuo, arrancar semana 2):**
  1. Definir ventanas de despliegue (lun-jue, 14:00-16:00 UTC) y runbooks de rollback con checklists.
  2. Documentar responsabilidades y contactos ante incidentes (rotación semanal on-call).
  3. Programar revisión semanal de performance con acciones acordadas y owners asignados.
- **Criterio de éxito:** Cero despliegues fuera de ventana y tiempos de respuesta < 30 min en incidentes.

## 8. Próximos entregables
- **Semana 1:** Export diario de métricas + alerta Telegram + grid de umbrales en paper.
- **Semana 2:** Canary live con límites duros + circuit breakers + panel inicial + gobernanza operativa.
- **Semana 3:** Ajustes de features/decay + observabilidad completa + runbooks documentados.

> Valores pueden ajustarse si la capacidad operativa lo requiere; documentar cualquier cambio antes de ejecutarlo.
