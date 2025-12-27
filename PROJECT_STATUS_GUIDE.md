# Estado del Proyecto y Guía de Comandos

## 1. Contexto del Proyecto: ¿Qué hemos construido?

Este sistema es un **Bot de Trading de Alta Frecuencia** para Polymarket y SX Bet.

### 🧠 El Cerebro (Estrategias)

1.  **Atomic Arbitrage (CTF)**: Compra sets completos de resultados y los divide/vende individualmente para capturar spread libre de riesgo.
2.  **Market Making (MM)**:
    *   **ML Signal Ensembler**: Un modelo de Machine Learning online que aprende de cada tick (spread coverage, volumen, etc.).
    *   **Whale Shadowing**: Sigue a las "ballenas" más rentables de Polymarket (detectadas automáticamente por el `WhaleHunter`). Si una ballena compra, el bot ajusta sus precios para seguir la tendencia.
    *   **Detección de Régimen**: Identifica si el mercado está *Volátil*, *Lateral* o en *Buzz Social* y ajusta el riesgo dinámicamente.
3.  **Paper Trading**: Actualmente operando en modo simulación ("Dry Run").
    *   Calcula PnL teórico y genera reportes CSV diarios.
    *   **Dashboard Premium**: Visualización gráfica (`dashboard.html`) para seguimiento de Equity y Drawdown.

### ⚡ Eficiencia (Nuevo)
*   **Smart Execution**: El bot ahora verifica cambios (Diff) antes de cancelar órdenes, reduciendo llamadas a la API un 80%.
*   **Signal Integration**: Conectado con Sentinel (Social) y Whale Hunter (On-Chain) para ajustar cotizaciones dinámicamente.

### 🛡️ Defensas (Risk Management)

*   **Canary Guard**: Detiene el bot si detecta pérdidas anómalas en pequeñas operaciones de prueba.
*   **Circuit Breakers**: Se activa ante latencia alta o desconexión de APIs.
*   **Drawdown Guard**: Frena el trading si el capital baja de cierto umbral diario.

---

## 2. Guía de Comandos GitHub

Para mantener el código sincronizado con el repositorio:

### 📥 Descargar cambios (Siempre haz esto antes de empezar)
```bash
git pull origin main
```
*Si hay conflictos (archivos modificados en ambos lados):*
```bash
git stash       # Guarda tus cambios temporalmente
git pull origin main
git stash pop   # Aplica tus cambios sobre lo nuevo (puede requerir resolver conflictos)
```

### 📤 Subir tus cambios
```bash
git add .
git commit -m "Descripción breve de lo que hiciste"
git push origin main
```

---

## 3. Guía de Comandos Servidor (OCI / Opera)

### 🚀 Despliegue Rápido
Desde tu máquina local (Windows), para actualizar el servidor con el último código:
```powershell
.\deploy_fast.ps1
```
*(Este script empaqueta el código, lo sube y reinicia los contenedores Docker automáticamente)*.

### 📡 Conexión SSH (Entrar al servidor)
```powershell
ssh -i "C:\Users\alons\Downloads\ssh-key-2025-12-04.key" ubuntu@158.179.214.56
```

### 📋 Ver Logs en Vivo (Monitorización)
Una vez dentro del servidor (`ssh`):
```bash
# Ver logs del scanner de arbitraje (y market maker)
cd /home/ubuntu/arbitrage_platform
docker-compose logs -f --tail=100 arbitrage_scanner
```
*Presiona `Ctrl+C` para salir de los logs.*

### 🛑 Detener/Reiniciar el Bot (En el servidor)
```bash
cd /home/ubuntu/arbitrage_platform
# Reiniciar
docker-compose restart arbitrage_scanner
# Detener completamente
docker-compose down
# Iniciar (si estaba detenido)
docker-compose up -d
```

---

## 4. Archivos Importantes

*   `automated_bot.py`: El cerebro principal. Coordina los scanners y el Market Maker.
*   `src/strategies/market_maker.py`: La lógica compleja de MM, ML y Whale Shadowing.
*   `config.py`: Variables de entorno, claves API y configuración de ballenas.
*   `PROXIMOS_PASOS.md`: (Reciente) Lista de tareas pendientes generada por el colaborador.
