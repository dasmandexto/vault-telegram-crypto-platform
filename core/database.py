import aiosqlite
import datetime
import uuid
from typing import List, Dict, Any, Optional, Tuple
from config import settings, SUPPORTED_COINS

from contextlib import asynccontextmanager

DB_FILE = settings.DATABASE_PATH

@asynccontextmanager
async def get_db():
    conn = await aiosqlite.connect(DB_FILE)
    conn.row_factory = aiosqlite.Row
    try:
        yield conn
    finally:
        await conn.close()

async def init_db():
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        
        # Таблица пользователей
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_blocked INTEGER DEFAULT 0,
            created_at TEXT,
            last_active TEXT
        )
        """)

        # Таблица кошельков по каждой монете
        await db.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            coin TEXT NOT NULL,
            network TEXT,
            address TEXT,
            memo TEXT,
            balance REAL DEFAULT 0.0,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(user_id, coin),
            FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
        )
        """)

        # Таблица запросов на создание/присвоение кошелька
        await db.execute("""
        CREATE TABLE IF NOT EXISTS wallet_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            coin TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
        )
        """)

        # Таблица транзакций (выводы, пополнения, обмены, ручные операции)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,          -- 'deposit', 'withdraw', 'exchange', 'p2p', 'manual_adjust'
            coin TEXT NOT NULL,
            amount REAL NOT NULL,
            to_address TEXT,
            memo TEXT,
            tx_hash TEXT,
            status TEXT NOT NULL,        -- 'pending', 'completed', 'rejected'
            comment TEXT,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
        )
        """)

        # Таблица истории рассылок
        await db.execute("""
        CREATE TABLE IF NOT EXISTS broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            target TEXT NOT NULL,
            recipients_count INTEGER DEFAULT 0,
            sent_at TEXT
        )
        """)

        # Таблица логов действий админа
        await db.execute("""
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT
        )
        """)

        # Таблица ставок бинарных опционов
        await db.execute("""
        CREATE TABLE IF NOT EXISTS binary_bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,
            stake_amount REAL NOT NULL,
            stake_coin TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            duration_seconds INTEGER NOT NULL,
            payout_rate REAL DEFAULT 0.85,
            payout_amount REAL DEFAULT 0.0,
            status TEXT DEFAULT 'active',
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
        )
        """)

        # Таблица спотовых ордеров
        await db.execute("""
        CREATE TABLE IF NOT EXISTS spot_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pair TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT DEFAULT 'MARKET',
            price REAL NOT NULL,
            amount REAL NOT NULL,
            total REAL NOT NULL,
            status TEXT DEFAULT 'filled',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
        )
        """)

        # Таблица фьючерсных позиций (Контрактная торговля в USDT)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS futures_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            pair TEXT NOT NULL,
            side TEXT NOT NULL,
            margin REAL NOT NULL,
            leverage INTEGER DEFAULT 10,
            entry_price REAL NOT NULL,
            close_price REAL,
            pnl REAL,
            status TEXT DEFAULT 'open',
            created_at TEXT NOT NULL,
            closed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(telegram_id) ON DELETE CASCADE
        )
        """)

        # Таблица системных настроек (включая HD Master Mnemonic)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )
        """)

        await db.commit()

async def get_or_create_user(telegram_id: int, username: Optional[str] = None, first_name: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.datetime.utcnow().isoformat()
    async with get_db() as db:
        async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                # Обновляем last_active и имя/username
                await db.execute(
                    "UPDATE users SET username = COALESCE(?, username), first_name = COALESCE(?, first_name), last_active = ? WHERE telegram_id = ?",
                    (username, first_name, now, telegram_id)
                )
                await db.commit()
                return dict(row)

        # Создаем нового пользователя
        await db.execute(
            "INSERT INTO users (telegram_id, username, first_name, is_blocked, created_at, last_active) VALUES (?, ?, ?, 0, ?, ?)",
            (telegram_id, username or "", first_name or "", now, now)
        )
        
        # Инициализируем записи по всем 10 монетам с нулевым балансом
        for coin, coin_info in SUPPORTED_COINS.items():
            await db.execute(
                """INSERT OR IGNORE INTO wallets (user_id, coin, network, address, memo, balance, created_at, updated_at) 
                   VALUES (?, ?, ?, NULL, NULL, 0.0, ?, ?)""",
                (telegram_id, coin, coin_info["network"], now, now)
            )
        await db.commit()

    return await get_user(telegram_id)

async def get_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    clean_username = username.lstrip("@").lower()
    async with get_db() as db:
        async with db.execute("SELECT * FROM users WHERE LOWER(username) = ?", (clean_username,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_user_wallets(telegram_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        # Убедимся, что все 10 монет есть в базе для юзера
        now = datetime.datetime.utcnow().isoformat()
        for coin, coin_info in SUPPORTED_COINS.items():
            await db.execute(
                """INSERT OR IGNORE INTO wallets (user_id, coin, network, address, memo, balance, created_at, updated_at) 
                   VALUES (?, ?, ?, NULL, NULL, 0.0, ?, ?)""",
                (telegram_id, coin, coin_info["network"], now, now)
            )
        await db.commit()

        async with db.execute("SELECT * FROM wallets WHERE user_id = ? ORDER BY id ASC", (telegram_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_wallet(user_id: int, coin: str) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute("SELECT * FROM wallets WHERE user_id = ? AND coin = ?", (user_id, coin.upper())) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def set_wallet_address(user_id: int, coin: str, address: str, memo: Optional[str] = None) -> bool:
    now = datetime.datetime.utcnow().isoformat()
    coin = coin.upper()
    async with get_db() as db:
        # Обновляем адрес
        await db.execute(
            """UPDATE wallets SET address = ?, memo = ?, updated_at = ? WHERE user_id = ? AND coin = ?""",
            (address.strip(), memo.strip() if memo else None, now, user_id, coin)
        )
        # Отмечаем связанные запросы как выполненные
        await db.execute(
            """UPDATE wallet_requests SET status = 'completed' WHERE user_id = ? AND coin = ? AND status = 'pending'""",
            (user_id, coin)
        )
        await db.commit()
        return True

async def adjust_balance(user_id: int, coin: str, delta_amount: float, comment: str = "") -> Tuple[bool, float]:
    """
    Изменяет баланс на delta_amount (может быть положительным или отрицательным).
    Возвращает (успех, новый_баланс).
    """
    now = datetime.datetime.utcnow().isoformat()
    coin = coin.upper()
    async with get_db() as db:
        async with db.execute("SELECT balance FROM wallets WHERE user_id = ? AND coin = ?", (user_id, coin)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False, 0.0
            current_balance = row["balance"]

        new_balance = current_balance + delta_amount
        if new_balance < 0:
            return False, current_balance

        await db.execute(
            "UPDATE wallets SET balance = ?, updated_at = ? WHERE user_id = ? AND coin = ?",
            (new_balance, now, user_id, coin)
        )
        await db.commit()
        return True, new_balance

async def create_wallet_request(user_id: int, coin: str) -> int:
    now = datetime.datetime.utcnow().isoformat()
    coin = coin.upper()
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO wallet_requests (user_id, coin, status, created_at) VALUES (?, ?, 'pending', ?)",
            (user_id, coin, now)
        )
        await db.commit()
        return cursor.lastrowid

async def get_pending_wallet_requests() -> List[Dict[str, Any]]:
    async with get_db() as db:
        query = """
        SELECT wr.*, u.username, u.first_name 
        FROM wallet_requests wr
        JOIN users u ON u.telegram_id = wr.user_id
        WHERE wr.status = 'pending'
        ORDER BY wr.id DESC
        """
        async with db.execute(query) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def create_transaction(
    user_id: int,
    type_: str,
    coin: str,
    amount: float,
    to_address: Optional[str] = None,
    memo: Optional[str] = None,
    tx_hash: Optional[str] = None,
    status: str = "pending",
    comment: Optional[str] = None
) -> str:
    now = datetime.datetime.utcnow().isoformat()
    tx_id = f"tx_{uuid.uuid4().hex[:8]}"
    async with get_db() as db:
        await db.execute(
            """INSERT INTO transactions (id, user_id, type, coin, amount, to_address, memo, tx_hash, status, comment, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tx_id, user_id, type_, coin.upper(), amount, to_address, memo, tx_hash, status, comment, now, now)
        )
        await db.commit()
    return tx_id

async def get_transaction(tx_id: str) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        query = """
        SELECT t.*, u.username, u.first_name 
        FROM transactions t
        JOIN users u ON u.telegram_id = t.user_id
        WHERE t.id = ?
        """
        async with db.execute(query, (tx_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def update_transaction_status(tx_id: str, status: str, tx_hash: Optional[str] = None, comment: Optional[str] = None) -> bool:
    now = datetime.datetime.utcnow().isoformat()
    async with get_db() as db:
        await db.execute(
            """UPDATE transactions 
               SET status = ?, 
                   tx_hash = COALESCE(?, tx_hash), 
                   comment = COALESCE(?, comment), 
                   updated_at = ? 
               WHERE id = ?""",
            (status, tx_hash, comment, now, tx_id)
        )
        await db.commit()
        return True

async def get_user_transactions(user_id: int, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_all_transactions(status: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    async with get_db() as db:
        if status:
            query = """
            SELECT t.*, u.username, u.first_name 
            FROM transactions t
            JOIN users u ON u.telegram_id = t.user_id
            WHERE t.status = ?
            ORDER BY t.created_at DESC LIMIT ? OFFSET ?
            """
            args = (status, limit, offset)
        else:
            query = """
            SELECT t.*, u.username, u.first_name 
            FROM transactions t
            JOIN users u ON u.telegram_id = t.user_id
            ORDER BY t.created_at DESC LIMIT ? OFFSET ?
            """
            args = (limit, offset)
        async with db.execute(query, args) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_all_users(search: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    async with get_db() as db:
        if search:
            s = f"%{search.strip().lower()}%"
            query = """
            SELECT u.*, 
                   COUNT(DISTINCT w.id) as wallets_count,
                   COALESCE(SUM(w.balance), 0) as total_balance_raw
            FROM users u
            LEFT JOIN wallets w ON w.user_id = u.telegram_id
            WHERE LOWER(u.username) LIKE ? OR CAST(u.telegram_id AS TEXT) LIKE ? OR LOWER(u.first_name) LIKE ?
            GROUP BY u.telegram_id
            ORDER BY u.created_at DESC LIMIT ? OFFSET ?
            """
            args = (s, s, s, limit, offset)
        else:
            query = """
            SELECT u.*, 
                   COUNT(DISTINCT w.id) as wallets_count,
                   COALESCE(SUM(w.balance), 0) as total_balance_raw
            FROM users u
            LEFT JOIN wallets w ON w.user_id = u.telegram_id
            GROUP BY u.telegram_id
            ORDER BY u.created_at DESC LIMIT ? OFFSET ?
            """
            args = (limit, offset)
            
        async with db.execute(query, args) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def set_user_block(user_id: int, blocked: bool) -> bool:
    async with get_db() as db:
        await db.execute("UPDATE users SET is_blocked = ? WHERE telegram_id = ?", (1 if blocked else 0, user_id))
        await db.commit()
        return True

async def get_stats() -> Dict[str, Any]:
    async with get_db() as db:
        # Всего юзеров
        async with db.execute("SELECT COUNT(*) as cnt FROM users") as cur:
            users_total = (await cur.fetchone())["cnt"]
        
        # Ожидающие транзакции
        async with db.execute("SELECT COUNT(*) as cnt FROM transactions WHERE status = 'pending'") as cur:
            pending_tx = (await cur.fetchone())["cnt"]

        # Заблокированные юзеры
        async with db.execute("SELECT COUNT(*) as cnt FROM users WHERE is_blocked = 1") as cur:
            blocked_users = (await cur.fetchone())["cnt"]

        # Ожидающие запросы на кошельки
        async with db.execute("SELECT COUNT(*) as cnt FROM wallet_requests WHERE status = 'pending'") as cur:
            pending_wallets = (await cur.fetchone())["cnt"]

        # Оборот за 24 часа (выполненные транзакции)
        yesterday = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).isoformat()
        async with db.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(amount), 0) as vol FROM transactions WHERE status = 'completed' AND created_at >= ?", (yesterday,)) as cur:
            row = await cur.fetchone()
            vol_24h = row["vol"]

        return {
            "users_total": users_total,
            "pending_tx": pending_tx,
            "blocked_users": blocked_users,
            "pending_wallets": pending_wallets,
            "volume_24h": round(vol_24h, 2)
        }

async def save_broadcast(message: str, target: str, recipients_count: int) -> int:
    now = datetime.datetime.utcnow().isoformat()
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO broadcasts (message, target, recipients_count, sent_at) VALUES (?, ?, ?, ?)",
            (message, target, recipients_count, now)
        )
        await db.commit()
        return cur.lastrowid

async def get_broadcast_history() -> List[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute("SELECT * FROM broadcasts ORDER BY id DESC LIMIT 50") as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def log_admin_action(admin_id: Optional[int], action: str, details: str):
    now = datetime.datetime.utcnow().isoformat()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO admin_logs (admin_id, action, details, created_at) VALUES (?, ?, ?, ?)",
            (admin_id, action, details, now)
        )
        await db.commit()

# --- МЕТОДЫ БИНАРНЫХ ОПЦИОНОВ ---
async def create_binary_bet(
    user_id: int,
    pair: str,
    direction: str,
    stake_amount: float,
    stake_coin: str,
    entry_price: float,
    duration_seconds: int,
    payout_rate: float = 0.85
) -> int:
    now = datetime.datetime.utcnow()
    expires_at = (now + datetime.timedelta(seconds=duration_seconds)).isoformat()
    now_str = now.isoformat()

    async with get_db() as db:
        cur = await db.execute(
            """INSERT INTO binary_bets (
                user_id, pair, direction, stake_amount, stake_coin, entry_price, 
                duration_seconds, payout_rate, payout_amount, status, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.0, 'active', ?, ?)""",
            (user_id, pair.upper(), direction.upper(), stake_amount, stake_coin.upper(), entry_price, duration_seconds, payout_rate, expires_at, now_str)
        )
        await db.commit()
        return cur.lastrowid

async def get_active_binary_bets() -> List[Dict[str, Any]]:
    async with get_db() as db:
        query = """
        SELECT b.*, u.username, u.first_name 
        FROM binary_bets b
        JOIN users u ON u.telegram_id = b.user_id
        WHERE b.status = 'active'
        ORDER BY b.expires_at ASC
        """
        async with db.execute(query) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def resolve_binary_bet(bet_id: int, exit_price: float, status: str, payout_amount: float) -> bool:
    async with get_db() as db:
        await db.execute(
            """UPDATE binary_bets 
               SET exit_price = ?, status = ?, payout_amount = ? 
               WHERE id = ? AND status = 'active'""",
            (exit_price, status, payout_amount, bet_id)
        )
        await db.commit()
        return True

async def get_user_binary_bets(user_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM binary_bets WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def get_all_binary_bets(limit: int = 50) -> List[Dict[str, Any]]:
    async with get_db() as db:
        query = """
        SELECT b.*, u.username, u.first_name 
        FROM binary_bets b
        JOIN users u ON u.telegram_id = b.user_id
        ORDER BY b.id DESC LIMIT ?
        """
        async with db.execute(query, (limit,)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def get_binary_stats() -> Dict[str, Any]:
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) as total_bets, COALESCE(SUM(stake_amount), 0) as total_volume FROM binary_bets") as cur:
            row1 = await cur.fetchone()
        async with db.execute("SELECT COUNT(*) as active_bets FROM binary_bets WHERE status = 'active'") as cur:
            row2 = await cur.fetchone()
        async with db.execute("SELECT COUNT(*) as won_bets, COALESCE(SUM(payout_amount), 0) as total_payouts FROM binary_bets WHERE status = 'won'") as cur:
            row3 = await cur.fetchone()

        total_vol = row1["total_volume"]
        total_payout = row3["total_payouts"]
        house_profit = round(total_vol - total_payout, 2)

        return {
            "total_bets": row1["total_bets"],
            "active_bets": row2["active_bets"],
            "won_bets": row3["won_bets"],
            "total_volume": round(total_vol, 2),
            "total_payouts": round(total_payout, 2),
            "house_profit": house_profit
        }

# --- МЕТОДЫ СПОТОВОЙ ТОРГОВЛИ ---
async def create_spot_order(user_id: int, pair: str, side: str, price: float, amount: float, total: float) -> int:
    now = datetime.datetime.utcnow().isoformat()
    async with get_db() as db:
        cur = await db.execute(
            """INSERT INTO spot_orders (user_id, pair, side, order_type, price, amount, total, status, created_at)
               VALUES (?, ?, ?, 'MARKET', ?, ?, ?, 'filled', ?)""",
            (user_id, pair.upper(), side.upper(), price, amount, total, now)
        )
        await db.commit()
        return cur.lastrowid

async def get_user_spot_orders(user_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM spot_orders WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

# --- МЕТОДЫ ФЬЮЧЕРСНОЙ (КОНТРАКТНОЙ) ТОРГОВЛИ ---
async def create_futures_position(
    user_id: int,
    pair: str,
    side: str,
    margin: float,
    leverage: int,
    entry_price: float
) -> int:
    now = datetime.datetime.utcnow().isoformat()
    async with get_db() as db:
        cur = await db.execute(
            """INSERT INTO futures_positions (
                user_id, pair, side, margin, leverage, entry_price, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'open', ?)""",
            (user_id, pair.upper(), side.upper(), margin, leverage, entry_price, now)
        )
        await db.commit()
        return cur.lastrowid

async def get_user_open_futures(user_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            """SELECT * FROM futures_positions 
               WHERE user_id = ? AND status = 'open' 
               ORDER BY id DESC""",
            (user_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

async def get_futures_position(pos_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM futures_positions WHERE id = ?",
            (pos_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def close_futures_position(pos_id: int, close_price: float, pnl: float) -> bool:
    now = datetime.datetime.utcnow().isoformat()
    async with get_db() as db:
        await db.execute(
            """UPDATE futures_positions 
               SET status = 'closed', close_price = ?, pnl = ?, closed_at = ? 
               WHERE id = ? AND status = 'open'""",
            (close_price, pnl, now, pos_id)
        )
        await db.commit()
        return True

async def get_user_futures_history(user_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            """SELECT * FROM futures_positions 
               WHERE user_id = ? AND status = 'closed' 
               ORDER BY id DESC LIMIT ?""",
            (user_id, limit)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

# --- СИСТЕМНЫЕ НАСТРОЙКИ (HD WALLET И ДР.) ---
async def get_system_setting(key: str) -> Optional[str]:
    async with get_db() as db:
        async with db.execute("SELECT value FROM system_settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row["value"] if row else None

async def set_system_setting(key: str, value: str) -> bool:
    now = datetime.datetime.utcnow().isoformat()
    async with get_db() as db:
        await db.execute("""
            INSERT INTO system_settings (key, value, updated_at) 
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """, (key, value, now))
        await db.commit()
        return True

async def delete_system_setting(key: str) -> bool:
    async with get_db() as db:
        await db.execute("DELETE FROM system_settings WHERE key = ?", (key,))
        await db.commit()
        return True

async def get_project_name() -> str:
    val = await get_system_setting("project_name")
    if val and val.strip():
        return val.strip()
    return getattr(settings, "PROJECT_NAME", "Vault") or "Vault"

async def get_welcome_text(first_name: str = "", username: str = "") -> str:
    custom = await get_system_setting("welcome_text")
    p_name = await get_project_name()
    safe_name = first_name or username or "пользователь"
    
    if custom and custom.strip():
        # Подставляем переменные в кастомный текст
        res = custom.replace("{name}", safe_name).replace("{first_name}", safe_name)
        res = res.replace("{username}", f"@{username}" if username else safe_name)
        res = res.replace("{project_name}", p_name)
        return res

    # Стандартный шаблон по умолчанию
    return (
        f"👋 Здравствуйте, <b>{safe_name}</b>!\n\n"
        f"Добро пожаловать в мультивалютный криптокошелек <b>{p_name}</b>.\n\n"
        f"⚡ <b>Доступные возможности:</b>\n"
        f"• Хранение и операции с 10 топ-криптовалютами (BTC, ETH, USDT, TON, SOL, BNB, TRX, XRP, DOGE, USDC)\n"
        f"• Присвоение персональных адресов для пополнения\n"
        f"• Быстрый вывод и переводы средств\n"
        f"• Внутренний обмен валют\n"
        f"• Прозрачная история транзакций\n\n"
        f"Нажмите кнопку ниже, чтобы открыть кошелек 👇"
    )

