"""
Vault HD Master-Wallet Engine (BIP-39 / BIP-32 / BIP-44 / BIP-84)
Генерирует и управляет детерминированными адресами пользователей для всех поддерживаемых блокчейнов.
Все клиентские кошельки являются детерминированными потомками единой мастер-сид фразы.
"""

import hashlib
import logging
from typing import Dict, Any, Optional, List

from bip_utils import (
    Bip39MnemonicGenerator,
    Bip39SeedGenerator,
    Bip39WordsNum,
    Bip39MnemonicValidator,
    Bip44,
    Bip44Coins,
    Bip44Changes,
    Bip84,
    Bip84Coins
)

from config import settings, SUPPORTED_COINS
from core.database import get_system_setting, set_system_setting

logger = logging.getLogger("vault.hd")

_CACHED_MNEMONIC: Optional[str] = None
_CACHED_SEED_BYTES: Optional[bytes] = None

def get_user_index(user_id: int) -> int:
    """
    Преобразует 64-битный Telegram ID в допустимый 31-битный индекс BIP-32 (0 .. 2^31 - 1).
    Гарантирует детерминированность: один и тот же user_id всегда дает один и тот же индекс.
    """
    return abs(int(user_id)) % 2147483647

async def get_or_create_master_mnemonic() -> str:
    """
    Получает сохраненную мастер-мнемонику (24 слова) или генерирует новую при первом запуске.
    Мнемоника надежно сохраняется в таблице system_settings в SQLite.
    """
    global _CACHED_MNEMONIC, _CACHED_SEED_BYTES

    if _CACHED_MNEMONIC:
        return _CACHED_MNEMONIC

    # 1. Проверяем настройку в config/env
    if getattr(settings, "HD_MASTER_MNEMONIC", ""):
        m = settings.HD_MASTER_MNEMONIC.strip()
        if Bip39MnemonicValidator().IsValid(m):
            _CACHED_MNEMONIC = m
            _CACHED_SEED_BYTES = Bip39SeedGenerator(m).Generate()
            return _CACHED_MNEMONIC

    # 2. Проверяем базу данных
    m_db = await get_system_setting("hd_master_mnemonic")
    if m_db and Bip39MnemonicValidator().IsValid(m_db.strip()):
        _CACHED_MNEMONIC = m_db.strip()
        _CACHED_SEED_BYTES = Bip39SeedGenerator(_CACHED_MNEMONIC).Generate()
        return _CACHED_MNEMONIC

    # 3. Генерируем новую надежную 24-словную мнемонику
    logger.info("Генерация новой 24-словной мастер-сид мнемоники BIP-39...")
    gen_mnemonic = Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_24).ToStr()
    await set_system_setting("hd_master_mnemonic", gen_mnemonic)
    
    _CACHED_MNEMONIC = gen_mnemonic
    _CACHED_SEED_BYTES = Bip39SeedGenerator(_CACHED_MNEMONIC).Generate()
    logger.info("Мастер-мнемоника успешно сохранена в базе данных.")
    return _CACHED_MNEMONIC

async def get_master_seed() -> bytes:
    global _CACHED_SEED_BYTES
    if _CACHED_SEED_BYTES is None:
        await get_or_create_master_mnemonic()
    return _CACHED_SEED_BYTES

async def derive_user_wallet(user_id: int, coin_sym: str) -> Optional[Dict[str, Any]]:
    """
    Вычисляет персональный блокчейн-адрес и приватный ключ для конкретного пользователя и монеты.
    """
    coin_sym = coin_sym.upper()
    if coin_sym in ["USD", "RUB"]:
        # Для фиата используется режимный IBAN, а не блокчейн-деривация
        return None

    seed_bytes = await get_master_seed()
    safe_index = get_user_index(user_id)

    try:
        if coin_sym == "BTC":
            mst = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN)
            acc = mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(safe_index)
            return {
                "coin": "BTC",
                "address": acc.PublicKey().ToAddress(),
                "private_key": acc.PrivateKey().ToWif(),
                "path": f"m/84'/0'/0'/0/{safe_index}",
                "network": "Bitcoin Native (SegWit)"
            }

        elif coin_sym in ["USDT", "TRX"]:
            mst = Bip44.FromSeed(seed_bytes, Bip44Coins.TRON)
            acc = mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(safe_index)
            return {
                "coin": coin_sym,
                "address": acc.PublicKey().ToAddress(),
                "private_key": acc.PrivateKey().Raw().ToHex(),
                "path": f"m/44'/195'/0'/0/{safe_index}",
                "network": "TRC-20" if coin_sym == "USDT" else "Tron Native"
            }

        elif coin_sym in ["ETH", "BNB", "USDC"]:
            bip_coin = Bip44Coins.ETHEREUM if coin_sym != "BNB" else Bip44Coins.BINANCE_SMART_CHAIN
            mst = Bip44.FromSeed(seed_bytes, bip_coin)
            acc = mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(safe_index)
            c_num = 60 if coin_sym in ["ETH", "USDC"] else 714
            return {
                "coin": coin_sym,
                "address": acc.PublicKey().ToAddress(),
                "private_key": acc.PrivateKey().Raw().ToHex(),
                "path": f"m/44'/{c_num}'/0'/0/{safe_index}",
                "network": "ERC-20" if coin_sym in ["ETH", "USDC"] else "BEP-20 (BSC)"
            }

        elif coin_sym == "TON":
            mst = Bip44.FromSeed(seed_bytes, Bip44Coins.TON)
            acc = mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(safe_index)
            return {
                "coin": "TON",
                "address": acc.PublicKey().ToAddress(),
                "private_key": acc.PrivateKey().Raw().ToHex(),
                "path": f"m/44'/607'/0'/0/{safe_index}",
                "network": "The Open Network (TON)"
            }

        elif coin_sym == "SOL":
            mst = Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
            acc = mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(safe_index)
            return {
                "coin": "SOL",
                "address": acc.PublicKey().ToAddress(),
                "private_key": acc.PrivateKey().Raw().ToHex(),
                "path": f"m/44'/501'/0'/0/{safe_index}",
                "network": "Solana Native"
            }

        elif coin_sym == "DOGE":
            mst = Bip44.FromSeed(seed_bytes, Bip44Coins.DOGECOIN)
            acc = mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(safe_index)
            return {
                "coin": "DOGE",
                "address": acc.PublicKey().ToAddress(),
                "private_key": acc.PrivateKey().ToWif(),
                "path": f"m/44'/3'/0'/0/{safe_index}",
                "network": "Dogecoin Native"
            }

        elif coin_sym == "XRP":
            mst = Bip44.FromSeed(seed_bytes, Bip44Coins.RIPPLE)
            acc = mst.Purpose().Coin().Account(0).Change(Bip44Changes.CHAIN_EXT).AddressIndex(safe_index)
            return {
                "coin": "XRP",
                "address": acc.PublicKey().ToAddress(),
                "private_key": acc.PrivateKey().Raw().ToHex(),
                "path": f"m/44'/144'/0'/0/{safe_index}",
                "network": "Ripple (XRP)"
            }

    except Exception as e:
        logger.error(f"Ошибка деривации кошелька {coin_sym} для user {user_id}: {e}")
        return None

    return None

async def derive_all_user_wallets(user_id: int) -> List[Dict[str, Any]]:
    """
    Вычисляет адреса и приватные ключи по всем поддерживаемым криптовалютам для указанного пользователя.
    """
    crypto_coins = ["BTC", "ETH", "USDT", "TON", "SOL", "BNB", "TRX", "XRP", "DOGE", "USDC"]
    results = []
    for coin in crypto_coins:
        w = await derive_user_wallet(user_id, coin)
        if w:
            results.append(w)
    return results

async def get_master_info(mask_mnemonic: bool = True) -> Dict[str, Any]:
    """
    Возвращает информацию о мастер-кошельке для админ-панели.
    """
    mnemonic = await get_or_create_master_mnemonic()
    words = mnemonic.split()
    fingerprint = hashlib.sha256(mnemonic.encode()).hexdigest()[:12]

    if mask_mnemonic:
        masked = f"{words[0]} {words[1]} ... {words[-2]} {words[-1]}"
    else:
        masked = mnemonic

    return {
        "status": "active",
        "standard": "BIP-39 / BIP-44 / BIP-84",
        "words_count": len(words),
        "fingerprint": fingerprint,
        "mnemonic": masked,
        "supported_coins_count": 10
    }
