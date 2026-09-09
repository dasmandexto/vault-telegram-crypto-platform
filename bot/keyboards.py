from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    WebAppInfo
)
from config import settings

def get_client_main_keyboard() -> ReplyKeyboardMarkup:
    base = settings.WEBAPP_URL or "https://telegram.org"
    url = f"{base}/?v=5" if not base.endswith("/") else f"{base}?v=5"
    kb = [
        [KeyboardButton(text="⚡ Открыть кошелёк", web_app=WebAppInfo(url=url))]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_client_inline_keyboard() -> InlineKeyboardMarkup:
    base = settings.WEBAPP_URL or "https://telegram.org"
    url = f"{base}/?v=5" if not base.endswith("/") else f"{base}?v=5"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Запустить WebApp Кошелек", web_app=WebAppInfo(url=url))]
    ])

def get_admin_transfer_keyboard(tx_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"tx_approve:{tx_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"tx_reject:{tx_id}")
        ]
    ])

def get_admin_wallet_request_keyboard(user_id: int, coin: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔑 Присвоить адрес", callback_data=f"set_w:{user_id}:{coin}")
        ]
    ])

def get_admin_webapp_keyboard() -> InlineKeyboardMarkup:
    admin_url = f"{settings.WEBAPP_URL}/admin" if settings.WEBAPP_URL else "https://telegram.org"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Открыть панель управления (WebApp)", web_app=WebAppInfo(url=admin_url))]
    ])

def get_admin_menu_keyboard() -> InlineKeyboardMarkup:
    admin_url = f"{settings.WEBAPP_URL}/admin" if settings.WEBAPP_URL else "https://telegram.org"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Открыть панель управления (WebApp)", web_app=WebAppInfo(url=admin_url))],
        [InlineKeyboardButton(text="⚙️ Настройки платформы и бота", callback_data="admin:settings")]
    ])

def get_admin_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Изменить текст приветствия", callback_data="admin:set_welcome")],
        [InlineKeyboardButton(text="🏷️ Изменить название кошелька", callback_data="admin:set_name")],
        [InlineKeyboardButton(text="💬 Изменить контакт поддержки", callback_data="admin:set_support")],
        [
            InlineKeyboardButton(text="👁️ Предпросмотр", callback_data="admin:preview_welcome"),
            InlineKeyboardButton(text="🔄 Сброс текста", callback_data="admin:reset_welcome")
        ],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="admin:menu")]
    ])

def get_admin_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel_input")]
    ])

