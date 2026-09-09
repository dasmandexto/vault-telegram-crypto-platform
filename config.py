import os
from typing import List, Dict, Any
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "Vault")
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS_RAW: str = os.getenv("ADMIN_IDS", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "vault-default-insecure-secret-key-32chars")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin12345")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    WEBAPP_URL: str = os.getenv("WEBAPP_URL", "")
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "vault.db")
    HD_MASTER_MNEMONIC: str = os.getenv("HD_MASTER_MNEMONIC", "")

    @property
    def admin_ids(self) -> List[int]:
        if not self.ADMIN_IDS_RAW:
            return []
        ids = []
        for part in self.ADMIN_IDS_RAW.split(","):
            part = part.strip()
            if part.isdigit() or (part.startswith("-") and part[1:].isdigit()):
                ids.append(int(part))
        return ids

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()

# 10 Самых актуальных криптовалют
SUPPORTED_COINS: Dict[str, Dict[str, Any]] = {
    "BTC": {
        "name": "Bitcoin",
        "symbol": "BTC",
        "network": "Bitcoin Native",
        "icon": "₿",
        "color": "#f7931a",
        "default_rate": 65000.0,
        "coingecko_id": "bitcoin",
        "decimals": 8,
        "has_memo": False
    },
    "ETH": {
        "name": "Ethereum",
        "symbol": "ETH",
        "network": "ERC-20",
        "icon": "Ξ",
        "color": "#627eea",
        "default_rate": 3450.0,
        "coingecko_id": "ethereum",
        "decimals": 6,
        "has_memo": False
    },
    "USDT": {
        "name": "Tether USD",
        "symbol": "USDT",
        "network": "TRC-20",
        "icon": "₮",
        "color": "#26a17b",
        "default_rate": 1.0,
        "coingecko_id": "tether",
        "decimals": 2,
        "has_memo": False
    },
    "TON": {
        "name": "Toncoin",
        "symbol": "TON",
        "network": "The Open Network",
        "icon": "💎",
        "color": "#0098ea",
        "default_rate": 6.80,
        "coingecko_id": "the-open-network",
        "decimals": 4,
        "has_memo": True
    },
    "SOL": {
        "name": "Solana",
        "symbol": "SOL",
        "network": "Solana Native",
        "icon": "◎",
        "color": "#14f195",
        "default_rate": 155.0,
        "coingecko_id": "solana",
        "decimals": 4,
        "has_memo": False
    },
    "BNB": {
        "name": "BNB",
        "symbol": "BNB",
        "network": "BEP-20",
        "icon": "🟡",
        "color": "#f3ba2f",
        "default_rate": 590.0,
        "coingecko_id": "binancecoin",
        "decimals": 4,
        "has_memo": False
    },
    "TRX": {
        "name": "TRON",
        "symbol": "TRX",
        "network": "TRC-20",
        "icon": "🔴",
        "color": "#ef0027",
        "default_rate": 0.125,
        "coingecko_id": "tron",
        "decimals": 4,
        "has_memo": False
    },
    "XRP": {
        "name": "Ripple",
        "symbol": "XRP",
        "network": "Ripple Native",
        "icon": "✕",
        "color": "#23292f",
        "default_rate": 0.58,
        "coingecko_id": "ripple",
        "decimals": 4,
        "has_memo": True
    },
    "DOGE": {
        "name": "Dogecoin",
        "symbol": "DOGE",
        "network": "Dogecoin Native",
        "icon": "Ð",
        "color": "#c2a633",
        "default_rate": 0.14,
        "coingecko_id": "dogecoin",
        "decimals": 4,
        "has_memo": False
    },
    "USDC": {
        "name": "USD Coin",
        "symbol": "USDC",
        "network": "ERC-20 / Solana",
        "icon": "💲",
        "color": "#2775ca",
        "default_rate": 1.0,
        "coingecko_id": "usd-coin",
        "decimals": 2,
        "has_memo": False,
        "is_fiat": False
    },
    "USD": {
        "name": "US Dollar",
        "symbol": "USD",
        "network": "IBAN / SWIFT / Wire",
        "icon": "$",
        "color": "#10b981",
        "default_rate": 1.0,
        "coingecko_id": "",
        "decimals": 2,
        "has_memo": False,
        "is_fiat": True
    },
    "RUB": {
        "name": "Российский рубль",
        "symbol": "RUB",
        "network": "СБП / Карта / Счет",
        "icon": "₽",
        "color": "#3b82f6",
        "default_rate": 0.0108,
        "coingecko_id": "",
        "decimals": 2,
        "has_memo": False,
        "is_fiat": True
    }
}

TRADING_PAIRS: List[Dict[str, Any]] = [
    {"pair": "BTC/USDT", "base": "BTC", "quote": "USDT", "binance": "BTCUSDT", "decimals": 2},
    {"pair": "ETH/USDT", "base": "ETH", "quote": "USDT", "binance": "ETHUSDT", "decimals": 2},
    {"pair": "SOL/USDT", "base": "SOL", "quote": "USDT", "binance": "SOLUSDT", "decimals": 2},
    {"pair": "TON/USDT", "base": "TON", "quote": "USDT", "binance": "TONUSDT", "decimals": 3},
    {"pair": "BNB/USDT", "base": "BNB", "quote": "USDT", "binance": "BNBUSDT", "decimals": 2},
    {"pair": "XRP/USDT", "base": "XRP", "quote": "USDT", "binance": "XRPUSDT", "decimals": 4},
    {"pair": "USDT/RUB", "base": "USDT", "quote": "RUB", "binance": "USDTRUB", "decimals": 2},
    {"pair": "BTC/USD", "base": "BTC", "quote": "USD", "binance": "BTCUSDT", "decimals": 2}
]

BINARY_CONFIG = {
    "default_payout_rate": 0.85,
    "expirations": [30, 60, 180, 300],
    "min_stake": 1.0,
    "max_stake": 100000.0
}
