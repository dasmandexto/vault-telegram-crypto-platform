import httpx
import asyncio
import time
import random
from typing import Dict, List, Any, Optional
from config import SUPPORTED_COINS, TRADING_PAIRS

_cached_rates: Dict[str, float] = {coin: info["default_rate"] for coin, info in SUPPORTED_COINS.items()}
_last_update_time: float = 0.0
_CACHE_TTL_SECONDS = 60.0

# Кэш для торговых котировок (обновляется быстро: 1 сек)
_cached_pair_prices: Dict[str, float] = {
    "BTC/USDT": 65000.0,
    "ETH/USDT": 3450.0,
    "SOL/USDT": 155.0,
    "TON/USDT": 6.80,
    "BNB/USDT": 590.0,
    "XRP/USDT": 0.58,
    "USDT/RUB": 92.50,
    "BTC/USD": 65000.0
}
_last_pair_update_time: float = 0.0

async def get_exchange_rates() -> Dict[str, float]:
    global _cached_rates, _last_update_time
    now = time.time()

    if now - _last_update_time < _CACHE_TTL_SECONDS:
        return _cached_rates

    try:
        # Для крипты с coingecko id
        ids = ",".join(info["coingecko_id"] for info in SUPPORTED_COINS.values() if info.get("coingecko_id"))
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd"
        
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                new_rates = {}
                for coin, info in SUPPORTED_COINS.items():
                    cg_id = info.get("coingecko_id")
                    if cg_id and cg_id in data and "usd" in data[cg_id]:
                        new_rates[coin] = float(data[cg_id]["usd"])
                    else:
                        new_rates[coin] = _cached_rates.get(coin, info["default_rate"])
                
                # Фиатные валюты
                new_rates["USD"] = 1.0
                new_rates["RUB"] = round(1.0 / _cached_pair_prices.get("USDT/RUB", 92.5), 6)

                _cached_rates = new_rates
                _last_update_time = now
    except Exception:
        pass

    return _cached_rates

async def get_all_pair_prices() -> Dict[str, float]:
    """
    Получает живые котировки торговых пар с Binance API (кэш 1 секунда)
    """
    global _cached_pair_prices, _last_pair_update_time
    now = time.time()

    if now - _last_pair_update_time < 1.0:
        return _cached_pair_prices

    try:
        symbols = ['"BTCUSDT"', '"ETHUSDT"', '"SOLUSDT"', '"BNBUSDT"']
        url = f"https://api.binance.us/api/v3/ticker/price?symbols=[{','.join(symbols)}]"
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                for item in data:
                    s = item["symbol"]
                    p = float(item["price"])
                    if s == "BTCUSDT":
                        _cached_pair_prices["BTC/USDT"] = p
                        _cached_pair_prices["BTC/USD"] = p
                    elif s == "ETHUSDT":
                        _cached_pair_prices["ETH/USDT"] = p
                    elif s == "SOLUSDT":
                        _cached_pair_prices["SOL/USDT"] = p
                    elif s == "BNBUSDT":
                        _cached_pair_prices["BNB/USDT"] = p
                _last_pair_update_time = now
    except Exception:
        # Небольшая живая микрофлуктуация (тикер живет) при сетевой паузе
        for p in _cached_pair_prices:
            if p != "USDT/RUB":
                delta = _cached_pair_prices[p] * random.uniform(-0.0005, 0.0005)
                _cached_pair_prices[p] = round(_cached_pair_prices[p] + delta, 4)

    # Обновляем TON и XRP из CoinGecko
    if _cached_rates.get("TON"):
        _cached_pair_prices["TON/USDT"] = _cached_rates["TON"]
    if _cached_rates.get("XRP"):
        _cached_pair_prices["XRP/USDT"] = _cached_rates["XRP"]

    return _cached_pair_prices

async def get_pair_price(pair: str) -> float:
    pair = pair.upper()
    prices = await get_all_pair_prices()
    if pair in prices:
        return prices[pair]
    
    # Поиск по базе/квоте
    for p in TRADING_PAIRS:
        if p["pair"].upper() == pair:
            return prices.get(p["pair"], 1.0)
    return 1.0

async def get_chart_data(pair: str, timeframe: str = "1m", limit: int = 40) -> List[Dict[str, Any]]:
    """
    Возвращает свечные данные [time, open, high, low, close, volume] для интерактивного графика.
    Поддерживаемые таймфреймы: 1m, 5m, 15m, 1h, 4h, 12h, 1d (24h), 1w, 1M, 1y.
    """
    binance_symbol = None
    for p in TRADING_PAIRS:
        if p["pair"].upper() == pair.upper():
            binance_symbol = p.get("binance")
            break

    # Нормализация таймфрейма для Binance
    tf_normalized = timeframe.strip()
    if tf_normalized == "24h":
        tf_binance = "1d"
    elif tf_normalized == "1y":
        tf_binance = "1M"
        limit = min(limit, 12)
    elif tf_normalized in ["1m", "5m", "15m", "1h", "4h", "12h", "1d", "1w", "1M"]:
        tf_binance = tf_normalized
    else:
        tf_binance = "1m"

    # 1. Попытка запросить реальные свечи с Binance.US
    if binance_symbol and binance_symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]:
        try:
            url = f"https://api.binance.us/api/v3/klines?symbol={binance_symbol}&interval={tf_binance}&limit={limit}"
            async with httpx.AsyncClient(timeout=3.5) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    raw = resp.json()
                    candles = []
                    for c in raw:
                        candles.append({
                            "time": int(c[0] // 1000),
                            "open": float(c[1]),
                            "high": float(c[2]),
                            "low": float(c[3]),
                            "close": float(c[4]),
                            "volume": float(c[5])
                        })
                    if len(candles) >= 2:
                        return candles
        except Exception:
            pass

    # 2. Фоллбэк: генерация реалистичных свечей с масштабируемой волатильностью
    current_price = await get_pair_price(pair)
    now_ts = int(time.time())

    step_map = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "4h": 14400,
        "12h": 43200,
        "1d": 86400,
        "24h": 86400,
        "1w": 604800,
        "1M": 2592000,
        "1y": 2592000
    }
    step = step_map.get(tf_normalized, 60)

    volatility_map = {
        "1m": 0.002,
        "5m": 0.004,
        "15m": 0.007,
        "1h": 0.012,
        "4h": 0.022,
        "12h": 0.035,
        "1d": 0.045,
        "24h": 0.045,
        "1w": 0.08,
        "1M": 0.15,
        "1y": 0.25
    }
    vol = volatility_map.get(tf_normalized, 0.003)

    decimals = 2 if current_price > 100 else (4 if current_price > 1 else 6)
    candles = []
    price = current_price * (1 - (limit * vol * 0.2))

    for i in range(limit):
        t = now_ts - (limit - i) * step
        o = price
        change = o * random.uniform(-vol, vol)
        c = round(o + change, decimals)
        high_extra = abs(change) * random.uniform(0.1, 0.6) + (o * vol * random.uniform(0.05, 0.2))
        low_extra = abs(change) * random.uniform(0.1, 0.6) + (o * vol * random.uniform(0.05, 0.2))
        h = round(max(o, c) + high_extra, decimals)
        l = round(max(0.0001, min(o, c) - low_extra), decimals)
        candles.append({
            "time": t,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": round(random.uniform(10, 100), 2)
        })
        price = c

    # Последняя свеча синхронизируется с живой текущей ценой
    candles[-1]["close"] = current_price
    candles[-1]["high"] = max(candles[-1]["high"], current_price)
    candles[-1]["low"] = min(candles[-1]["low"], current_price)
    return candles

def convert_to_usd(coin: str, amount: float, rates: Dict[str, float]) -> float:
    coin_upper = coin.upper()
    if coin_upper == "USD":
        return round(amount, 2)
    if coin_upper == "RUB":
        rate = rates.get("RUB", 0.0108)
        return round(amount * rate, 2)
    rate = rates.get(coin_upper, SUPPORTED_COINS.get(coin_upper, {}).get("default_rate", 1.0))
    return round(amount * rate, 2)
