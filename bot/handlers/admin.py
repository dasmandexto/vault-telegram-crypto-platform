from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import settings
from core.database import (
    get_stats, 
    get_transaction, 
    update_transaction_status, 
    adjust_balance, 
    set_wallet_address,
    get_user,
    log_admin_action
)
from bot.keyboards import get_admin_webapp_keyboard
from bot.notifier import notify_client_transfer_status, notify_client_wallet_assigned

router = Router(name="admin_router")

class AdminStates(StatesGroup):
    waiting_for_wallet_address = State()
    waiting_for_reject_reason = State()

def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids

@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ к панели администратора запрещен.")
        return

    stats = await get_stats()
    text = (
        "⚡ <b>Панель управления Vault (GOD MODE)</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['users_total']}</b>\n"
        f"⏳ Ожидают обработки транзакций: <b>{stats['pending_tx']}</b>\n"
        f"🔑 Ожидают кошельков: <b>{stats['pending_wallets']}</b>\n"
        f"📊 Оборот за 24 часа: <b>${stats['volume_24h']}</b>\n"
        f"🚫 Заблокировано: <b>{stats['blocked_users']}</b>\n\n"
        "Откройте полную веб-панель для детального управления 👇"
    )
    await message.answer(text, reply_markup=get_admin_webapp_keyboard())

# --- Обработка callback: Одобрение вывода ---
@router.callback_query(F.data.startswith("tx_approve:"))
async def callback_approve_tx(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!", show_alert=True)
        return

    tx_id = callback.data.split(":", 1)[1]
    tx = await get_transaction(tx_id)
    if not tx:
        await callback.answer("Заявка не найдена!", show_alert=True)
        return

    if tx["status"] != "pending":
        await callback.answer(f"Заявка уже в статусе: {tx['status']}", show_alert=True)
        return

    # Подтверждаем транзакцию
    await update_transaction_status(tx_id, status="completed", comment="Одобрено администратором через Telegram")
    await log_admin_action(callback.from_user.id, "approve_tx", f"Одобрена заявка {tx_id}")

    # Уведомляем клиента
    await notify_client_transfer_status(
        user_id=tx["user_id"],
        tx_id=tx_id,
        coin=tx["coin"],
        amount=tx["amount"],
        status="completed"
    )

    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ <b>Одобрено администратором @{callback.from_user.username or callback.from_user.id}</b>"
    )
    await callback.answer("Заявка успешно одобрена!")

# --- Обработка callback: Отклонение вывода ---
@router.callback_query(F.data.startswith("tx_reject:"))
async def callback_reject_tx(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!", show_alert=True)
        return

    tx_id = callback.data.split(":", 1)[1]
    tx = await get_transaction(tx_id)
    if not tx:
        await callback.answer("Заявка не найдена!", show_alert=True)
        return

    if tx["status"] != "pending":
        await callback.answer(f"Заявка уже в статусе: {tx['status']}", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_reject_reason)
    await state.update_data(tx_id=tx_id, msg_id=callback.message.message_id)

    await callback.message.reply("✏ <b>Введите причину отклонения</b> (или отправьте <code>-</code> без причины):")
    await callback.answer()

@router.message(AdminStates.waiting_for_reject_reason)
async def process_reject_reason(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    tx_id = data.get("tx_id")
    reason = message.text.strip()
    if reason == "-":
        reason = "Отклонено оператором"

    tx = await get_transaction(tx_id)
    if tx and tx["status"] == "pending":
        # Возвращаем средства на баланс пользователя
        await adjust_balance(tx["user_id"], tx["coin"], tx["amount"], comment=f"Возврат по заявке #{tx_id}")
        await update_transaction_status(tx_id, status="rejected", comment=reason)
        await log_admin_action(message.from_user.id, "reject_tx", f"Отклонена заявка {tx_id}: {reason}")

        # Уведомляем клиента
        await notify_client_transfer_status(
            user_id=tx["user_id"],
            tx_id=tx_id,
            coin=tx["coin"],
            amount=tx["amount"],
            status="rejected",
            reason=reason
        )

        await message.answer(f"❌ Заявка <code>#{tx_id}</code> отклонена. Средства возвращены клиенту.")

    await state.clear()

# --- Обработка callback: Назначение адреса кошелька ---
@router.callback_query(F.data.startswith("set_w:"))
async def callback_set_wallet(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав!", show_alert=True)
        return

    parts = callback.data.split(":")
    user_id = int(parts[1])
    coin = parts[2]

    user = await get_user(user_id)
    user_str = f"@{user['username']}" if user and user.get("username") else f"ID {user_id}"

    await state.set_state(AdminStates.waiting_for_wallet_address)
    await state.update_data(target_user_id=user_id, coin=coin)

    is_fiat = coin in ("USD", "RUB")
    term = "банковских реквизитов (IBAN)" if is_fiat else "адреса кошелька"
    placeholder = "IBAN / номер расчетного счета или карты" if is_fiat else "адрес кошелька"

    await callback.message.reply(
        f"🔑 <b>Назначение {term}</b>\n\n"
        f"Клиент: <b>{user_str}</b>\n"
        f"Валюта: <b>{coin}</b>\n\n"
        f"Отправьте {placeholder} сообщением в чат.\n"
        f"<i>(Если требуется БИК / банк / ФИО получателя / Memo, укажите на второй строке)</i>"
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_wallet_address)
async def process_wallet_address(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    coin = data.get("coin")

    lines = [line.strip() for line in message.text.split("\n") if line.strip()]
    address = lines[0]
    memo = lines[1] if len(lines) > 1 else None

    # Сохраняем адрес / IBAN
    await set_wallet_address(target_user_id, coin, address, memo)
    await log_admin_action(message.from_user.id, "set_wallet", f"Установлен реквизит {coin} для {target_user_id}: {address}")

    # Уведомляем клиента в Telegram
    await notify_client_wallet_assigned(target_user_id, coin, address, memo)

    memo_str = f" (Инфо: <code>{memo}</code>)" if memo else ""
    is_fiat = coin in ("USD", "RUB")
    term_success = "Реквизиты (IBAN) успешно назначены!" if is_fiat else "Адрес кошелька успешно назначен!"
    await message.answer(
        f"✅ <b>{term_success}</b>\n\n"
        f"Валюта: <b>{coin}</b>\n"
        f"Данные: <code>{address}</code>{memo_str}\n"
        f"Клиенту отправлено уведомление."
    )
    await state.clear()
