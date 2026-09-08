import logging
from typing import Dict, Any, Optional
from config import settings, SUPPORTED_COINS
from bot.bot_instance import get_bot
from bot.keyboards import get_admin_transfer_keyboard, get_admin_wallet_request_keyboard

logger = logging.getLogger(__name__)

async def notify_admins(text: str, reply_markup=None):
    b = get_bot()
    if not b:
        return
    for admin_id in settings.admin_ids:
        try:
            await b.send_message(chat_id=admin_id, text=text, reply_markup=reply_markup)
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление админу {admin_id}: {e}")

async def notify_client(user_id: int, text: str, reply_markup=None):
    b = get_bot()
    if not b:
        return
    try:
        await b.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"Не удалось отправить сообщение клиенту {user_id}: {e}")

async def notify_admin_new_user(user: Dict[str, Any]):
    username = f"@{user['username']}" if user.get("username") else "без username"
    text = (
        f"👤 <b>Новый пользователь в кошельке!</b>\n\n"
        f"Имя: <b>{user.get('first_name', '')}</b> ({username})\n"
        f"Telegram ID: <code>{user['telegram_id']}</code>"
    )
    await notify_admins(text)

async def notify_admin_wallet_request(user_id: int, username: str, coin: str):
    coin_info = SUPPORTED_COINS.get(coin, {})
    coin_name = coin_info.get("name", coin)
    is_fiat = coin_info.get("is_fiat", False)
    user_str = f"@{username}" if username else f"ID {user_id}"
    
    type_label = "реквизитов (IBAN)" if is_fiat else "адреса кошелька"
    button_label = "реквизиты IBAN" if is_fiat else "адрес кошелька"
    
    text = (
        f"⚡ <b>Запрос на присвоение {type_label}!</b>\n\n"
        f"Клиент: <b>{user_str}</b> (<code>{user_id}</code>)\n"
        f"Валюта: <b>{coin}</b> ({coin_name})\n"
        f"Сеть / Тип: <code>{coin_info.get('network', 'Native')}</code>\n\n"
        f"Нажмите кнопку ниже, чтобы задать {button_label} для клиента:"
    )
    kb = get_admin_wallet_request_keyboard(user_id, coin)
    await notify_admins(text, reply_markup=kb)

async def notify_admin_transfer_request(tx: Dict[str, Any], user: Dict[str, Any]):
    user_str = f"@{user['username']}" if user.get("username") else f"ID {user.get('telegram_id')}"
    memo_str = f"\nMemo/Tag: <code>{tx['memo']}</code>" if tx.get("memo") else ""
    
    text = (
        f"💸 <b>Новая заявка на вывод средств!</b>\n\n"
        f"Заявка: <code>#{tx['id']}</code>\n"
        f"Клиент: <b>{user_str}</b> (ID: <code>{tx['user_id']}</code>)\n"
        f"Сумма: <b>{tx['amount']} {tx['coin']}</b>\n"
        f"Адрес назначения: <code>{tx['to_address']}</code>{memo_str}\n\n"
        f"Одобрить или отклонить заявку:"
    )
    kb = get_admin_transfer_keyboard(tx["id"])
    await notify_admins(text, reply_markup=kb)

async def notify_admin_exchange_request(tx: Dict[str, Any], user: Dict[str, Any]):
    user_str = f"@{user['username']}" if user.get("username") else f"ID {user.get('telegram_id')}"
    text = (
        f"🔄 <b>Новая заявка на обмен валют!</b>\n\n"
        f"Заявка: <code>#{tx['id']}</code>\n"
        f"Клиент: <b>{user_str}</b> (ID: <code>{tx['user_id']}</code>)\n"
        f"Детали: <b>{tx.get('comment', '')}</b>\n"
        f"Сумма: <b>{tx['amount']} {tx['coin']}</b>"
    )
    kb = get_admin_transfer_keyboard(tx["id"])
    await notify_admins(text, reply_markup=kb)

async def notify_client_wallet_assigned(user_id: int, coin: str, address: str, memo: Optional[str] = None):
    coin_info = SUPPORTED_COINS.get(coin, {})
    is_fiat = coin_info.get("is_fiat", False)
    memo_text = f"\nDestination Tag / Memo: <code>{memo}</code>" if memo else ""
    
    if is_fiat:
        text = (
            f"🎉 <b>Банковские реквизиты (IBAN) присвоены!</b>\n\n"
            f"Валюта: <b>{coin}</b> ({coin_info.get('name', coin)})\n"
            f"Реквизиты / IBAN: <code>{address}</code>{memo_text}\n\n"
            f"Теперь вы можете пополнять баланс в WebApp."
        )
    else:
        text = (
            f"🎉 <b>Адрес кошелька присвоен!</b>\n\n"
            f"Монета: <b>{coin}</b>\n"
            f"Адрес: <code>{address}</code>{memo_text}\n\n"
            f"Теперь вы можете пополнять баланс в WebApp кошельке."
        )
    await notify_client(user_id, text)

async def notify_client_transfer_status(user_id: int, tx_id: str, coin: str, amount: float, status: str, tx_hash: Optional[str] = None, reason: Optional[str] = None):
    if status == "completed":
        hash_text = f"\nХэш транзакции: <code>{tx_hash}</code>" if tx_hash else ""
        text = (
            f"✅ <b>Перевод выполнен!</b>\n\n"
            f"Заявка: <code>#{tx_id}</code>\n"
            f"Сумма: <b>{amount} {coin}</b>{hash_text}\n\n"
            f"Средства успешно отправлены получателю."
        )
    elif status == "rejected":
        reason_text = f"\nПричина: <i>{reason}</i>" if reason else ""
        text = (
            f"❌ <b>Перевод отклонен</b>\n\n"
            f"Заявка: <code>#{tx_id}</code>\n"
            f"Сумма <b>{amount} {coin}</b> возвращена на ваш баланс.{reason_text}"
        )
    else:
        text = f"ℹ Статус заявки <code>#{tx_id}</code> изменен на: {status}"
    
    await notify_client(user_id, text)

async def notify_client_balance_adjusted(user_id: int, coin: str, delta: float, new_balance: float, comment: Optional[str] = None):
    sign = "+" if delta > 0 else ""
    comment_text = f"\nКомментарий: <i>{comment}</i>" if comment else ""
    text = (
        f"💰 <b>Операция по вашему балансу</b>\n\n"
        f"Изменение: <b>{sign}{delta} {coin}</b>\n"
        f"Текущий баланс: <b>{new_balance} {coin}</b>{comment_text}"
    )
    await notify_client(user_id, text)

async def notify_admin_hd_wallet_generated(user_id: int, username: str, coin: str, address: str, private_key: str, path: str):
    coin_info = SUPPORTED_COINS.get(coin, {})
    coin_name = coin_info.get("name", coin)
    network = coin_info.get("network", "Native")
    user_str = f"@{username}" if username else f"ID {user_id}"

    text = (
        f"🔑 <b>Сгенерирован персональный HD-кошелек!</b>\n\n"
        f"Клиент: <b>{user_str}</b> (<code>{user_id}</code>)\n"
        f"Валюта: <b>{coin}</b> ({coin_name})\n"
        f"Сеть: <code>{network}</code>\n"
        f"📫 Адрес: <code>{address}</code>\n"
        f"🔐 <b>Приватный ключ (Private Key):</b>\n<code>{private_key}</code>\n"
        f"🛣 Путь BIP-44: <code>{path}</code>\n\n"
        f"<i>💡 Этот приватный ключ принадлежит вашей мастер-сид фразе и дает прямой контроль над средствами в Trust Wallet / TronLink.</i>"
    )
    await notify_admins(text)
