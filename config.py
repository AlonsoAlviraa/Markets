import os
from dotenv import load_dotenv

load_dotenv()

# API Key Rotation Support
# Format: KEY1,KEY2,KEY3 (comma-separated)
ODDS_API_KEYS_RAW = os.getenv("ODDS_API_KEY", "")
ODDS_API_KEYS = [k.strip() for k in ODDS_API_KEYS_RAW.split(",") if k.strip()]

MIN_LIQUIDITY = int(os.getenv("MIN_LIQUIDITY", 500))
MIN_EV = float(os.getenv("MIN_EV", 0.05))

# Polymarket Configuration (Optional - for executing trades or orderbook depth)
POLY_HOST = os.getenv("POLY_HOST", "https://clob.polymarket.com")
POLY_KEY = os.getenv("POLY_KEY", "")  # Leave empty if not executing trades
POLY_SECRET = os.getenv("POLY_SECRET") # Private Key (careful!)
POLY_PASSPHRASE = os.getenv("POLY_PASSPHRASE")
poly_chain_id_str = os.getenv("POLY_CHAIN_ID", "137")
POLY_CHAIN_ID = int(poly_chain_id_str) if poly_chain_id_str and poly_chain_id_str.strip() else 137 # Polygon Mainnet

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Whale tracking configuration (used by spy/copy strategies)
WHALE_WALLETS_RAW = os.getenv("WHALE_WALLETS", "")
WHALE_WALLETS = [w.strip() for w in WHALE_WALLETS_RAW.split(",") if w.strip()]

if not ODDS_API_KEYS or len(ODDS_API_KEYS) == 0:
    # raise ValueError("ODDS_API_KEY not found in .env file")
    print("⚠️ WARN: ODDS_API_KEY not found. Sports Arbitrage Collectors will be disabled.")
