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
    log_admin_action,
    get_project_name,
    get_welcome_text,
    get_system_setting,
    set_system_setting,
    delete_system_setting
)
from bot.keyboards import (
    get_admin_webapp_keyboard,
    get_admin_menu_keyboard,
    get_admin_settings_keyboard,
    get_admin_cancel_keyboard
)
from bot.notifier import notify_client_transfer_status, notify_client_wallet_assigned

router = Router(name="admin_router")

class AdminStates(StatesGroup):
    waiting_for_wallet_address = State()
    waiting_for_reject_reason = State()
    waiting_for_welcome_text = State()
    waiting_for_project_name = State()
    waiting_for_support_contact = State()

def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids

async def render_admin_menu_text() -> str:
    p_name = await get_project_name()
    stats = await get_stats()
    return (
        f"⚡ <b>Панель управления {p_name} (GOD MODE)</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['users_total']}</b>\n"
        f"⏳ Ожидают обработки транзакций: <b>{stats['pending_tx']}</b>\n"
        f"🔑 Ожидают кошельков: <b>{stats['pending_wallets']}</b>\n"
        f"📊 Оборот за 24 часа: <b>${stats['volume_24h']}</b>\n"
        f"🚫 Заблокировано: <b>{stats['blocked_users']}</b>\n\n"
        "Выберите действие ниже 👇"
    )

async def render_settings_text() -> str:
    p_name = await get_project_name()
    support = await get_system_setting("support_contact") or "Не указан"
    custom_welcome = await get_system_setting("welcome_text")
    welcome_status = "Пользовательский ✏️" if custom_welcome else "Стандартный 📋"
    
    return (
        f"⚙️ <b>Настройки платформы и бота</b>\n\n"
        f"🏷️ <b>Название проекта:</b> <code>{p_name}</code>\n"
        f"💬 <b>Контакт поддержки:</b> <code>{support}</code>\n"
        f"📝 <b>Текст приветствия:</b> <i>{welcome_status}</i>\n\n"
        "💡 <i>Вы можете настроить название кошелька, текст приветствия (/start) и контакты поддержки.</i>"
    )

@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ к панели администратора запрещен.")
        return

    text = await render_admin_menu_text()
    await message.answer(text, reply_markup=get_admin_menu_keyboard())

@router.message(Command("settings"))
async def cmd_settings(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    text = await render_settings_text()
    await message.answer(text, reply_markup=get_admin_settings_keyboard())


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

# --- Настройки бота и платформы ---
@router.callback_query(F.data == "admin:menu")
async def callback_admin_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    text = await render_admin_menu_text()
    try:
        await callback.message.edit_text(text, reply_markup=get_admin_menu_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_admin_menu_keyboard())
    await callback.answer()

@router.callback_query(F.data == "admin:settings")
async def callback_admin_settings(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    text = await render_settings_text()
    try:
        await callback.message.edit_text(text, reply_markup=get_admin_settings_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=get_admin_settings_keyboard())
    await callback.answer()

@router.callback_query(F.data == "admin:cancel_input")
async def callback_cancel_input(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    text = await render_settings_text()
    try:
        await callback.message.edit_text(f"❌ Ввод отменен.\n\n{text}", reply_markup=get_admin_settings_keyboard())
    except Exception:
        await callback.message.answer("❌ Ввод отменен.", reply_markup=get_admin_settings_keyboard())
    await callback.answer()

@router.callback_query(F.data == "admin:set_name")
async def callback_set_name(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_project_name)
    current_name = await get_project_name()
    await callback.message.answer(
        f"🏷️ <b>Изменение названия проекта</b>\n\n"
        f"Текущее название: <b>{current_name}</b>\n\n"
        f"Отправьте новое название платформы в чат (например: <code>CryptoVault</code>):",
        reply_markup=get_admin_cancel_keyboard()
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_project_name)
async def process_project_name(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    new_name = message.text.strip()
    if not new_name or len(new_name) > 64:
        await message.answer("⚠️ Название должно быть длиной от 1 до 64 символов. Попробуйте еще раз:")
        return

    await set_system_setting("project_name", new_name)
    await log_admin_action(message.from_user.id, "set_project_name", f"Установлено название: {new_name}")
    await state.clear()
    
    text = await render_settings_text()
    await message.answer(f"✅ Название проекта изменено на <b>{new_name}</b>!\n\n{text}", reply_markup=get_admin_settings_keyboard())

@router.callback_query(F.data == "admin:set_support")
async def callback_set_support(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_support_contact)
    current_support = await get_system_setting("support_contact") or "Не указан"
    await callback.message.answer(
        f"💬 <b>Контакт технической поддержки</b>\n\n"
        f"Текущий контакт: <code>{current_support}</code>\n\n"
        f"Отправьте юзернейм (например: <code>@SupportBot</code>) или ссылку на саппорт:",
        reply_markup=get_admin_cancel_keyboard()
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_support_contact)
async def process_support_contact(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    contact = message.text.strip()
    await set_system_setting("support_contact", contact)
    await log_admin_action(message.from_user.id, "set_support_contact", f"Установлен контакт: {contact}")
    await state.clear()
    
    text = await render_settings_text()
    await message.answer(f"✅ Контакт поддержки сохранен: <code>{contact}</code>\n\n{text}", reply_markup=get_admin_settings_keyboard())

@router.callback_query(F.data == "admin:set_welcome")
async def callback_set_welcome(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AdminStates.waiting_for_welcome_text)
    await callback.message.answer(
        "📝 <b>Изменение приветственного сообщения</b>\n\n"
        "Отправьте новый текст приветствия бота для команды /start.\n\n"
        "Доступные переменные шаблона:\n"
        "• <code>{name}</code> — Имя пользователя\n"
        "• <code>{username}</code> — Юзернейм пользователя (@username)\n"
        "• <code>{project_name}</code> — Текущее название проекта\n\n"
        "Поддерживается HTML-разметка (<b>жирный</b>, <i>курсив</i>, <code>код</code>).",
        reply_markup=get_admin_cancel_keyboard()
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_welcome_text)
async def process_welcome_text(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text_val = message.text.strip()
    await set_system_setting("welcome_text", text_val)
    await log_admin_action(message.from_user.id, "set_welcome_text", "Обновлен шаблон приветствия")
    await state.clear()
    
    preview = await get_welcome_text(first_name=message.from_user.first_name or "", username=message.from_user.username or "")
    text = await render_settings_text()
    await message.answer(
        f"✅ Приветственное сообщение успешно обновлено!\n\n"
        f"<b>Предпросмотр:</b>\n{preview}\n\n{text}",
        reply_markup=get_admin_settings_keyboard()
    )

@router.callback_query(F.data == "admin:preview_welcome")
async def callback_preview_welcome(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    preview = await get_welcome_text(first_name=callback.from_user.first_name or "", username=callback.from_user.username or "")
    await callback.message.answer(
        f"👁️ <b>Предпросмотр приветствия (/start):</b>\n\n{preview}",
        reply_markup=get_admin_settings_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin:reset_welcome")
async def callback_reset_welcome(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await delete_system_setting("welcome_text")
    await log_admin_action(callback.from_user.id, "reset_welcome_text", "Сброшен шаблон приветствия к стандартному")
    text = await render_settings_text()
    await callback.message.answer(f"🔄 Текст приветствия сброшен к стандартному шаблону.\n\n{text}", reply_markup=get_admin_settings_keyboard())
    await callback.answer()

