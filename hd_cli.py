#!/usr/bin/env python3
"""
Vault HD Master-Wallet CLI
Консольная утилита для управления HD-кошельками и экспорта приватных ключей.
"""

import sys
import os
import asyncio
import csv
from datetime import datetime

# Обеспечиваем доступ к модулям
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core.hd_wallet import (
    get_or_create_master_mnemonic,
    get_master_info,
    derive_all_user_wallets,
    derive_user_wallet
)
from core.database import get_all_users, get_user

async def cmd_master():
    mnemonic = await get_or_create_master_mnemonic()
    info = await get_master_info(mask_mnemonic=False)
    print("=" * 60)
    print("🔑 VAULT HD MASTER-WALLET (BIP-39 / BIP-44 / BIP-84)")
    print("=" * 60)
    print(f"Стандарт:          {info['standard']}")
    print(f"Количество слов:   {info['words_count']}")
    print(f"Fingerprint:       {info['fingerprint']}")
    print("-" * 60)
    print("📜 МАСТЕР-СИД ФРАЗА (ХРАНИТЬ В СЕКРЕТЕ!):")
    print(mnemonic)
    print("=" * 60)
    print("💡 Вы можете импортировать эти 24 слова в Electrum или другой мульти-кошелек.")

async def cmd_user(user_id_str: str):
    try:
        user_id = int(user_id_str)
    except ValueError:
        print(f"Ошибка: Некорректный Telegram ID '{user_id_str}'")
        return

    user = await get_user(user_id)
    uname = f"@{user['username']}" if (user and user.get("username")) else "N/A"
    fname = user.get("first_name", "N/A") if user else "N/A"

    print("=" * 80)
    print(f"👤 ДЕТЕРМИНИРОВАННЫЕ КОШЕЛЬКИ ДЛЯ USER ID: {user_id} ({uname}, {fname})")
    print("=" * 80)

    wallets = await derive_all_user_wallets(user_id)
    for w in wallets:
        print(f"\n🪙 Монета:        {w['coin']} ({w['network']})")
        print(f"   📫 Адрес:       {w['address']}")
        print(f"   🛣 Путь BIP-44: {w['path']}")
        print(f"   🔐 Private Key: {w['private_key']}")
    print("\n" + "=" * 80)

async def cmd_export(filename: str = None):
    if not filename:
        filename = f"vault_hd_keys_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    users = await get_all_users(limit=10000)
    print(f"Экспорт ключей для {len(users)} пользователей в файл '{filename}'...")

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["User_ID", "Username", "First_Name", "Coin", "Network", "Address", "Derivation_Path", "Private_Key"])

        for u in users:
            uid = u["telegram_id"]
            wallets = await derive_all_user_wallets(uid)
            for w in wallets:
                writer.writerow([
                    uid,
                    u.get("username", ""),
                    u.get("first_name", ""),
                    w["coin"],
                    w["network"],
                    w["address"],
                    w["path"],
                    w["private_key"]
                ])

    print(f"✓ Успешно экспортировано! Файл: {filename}")

def print_help():
    print("""
Использование:
  python hd_cli.py master               - Показать мастер-сид фразу и статус
  python hd_cli.py user <telegram_id>   - Показать адреса и приватные ключи конкретного клиента
  python hd_cli.py export [файл.csv]    - Экспортировать все ключи всех пользователей в CSV
    """)

async def main():
    if len(sys.argv) < 2:
        print_help()
        return

    cmd = sys.argv[1].lower()
    if cmd == "master":
        await cmd_master()
    elif cmd == "user":
        if len(sys.argv) < 3:
            print("Укажите Telegram ID: python hd_cli.py user <telegram_id>")
            return
        await cmd_user(sys.argv[2])
    elif cmd == "export":
        fn = sys.argv[2] if len(sys.argv) > 2 else None
        await cmd_export(fn)
    else:
        print_help()

if __name__ == "__main__":
    asyncio.run(main())
