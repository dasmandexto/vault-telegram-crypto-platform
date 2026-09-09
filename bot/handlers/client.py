from aiogram import Router, types
from aiogram.filters import CommandStart, Command
from core.database import get_or_create_user, get_welcome_text, get_project_name
from bot.keyboards import get_client_main_keyboard, get_client_inline_keyboard
from bot.notifier import notify_admin_new_user

router = Router(name="client_router")

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    telegram_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    # Создаем или получаем пользователя
    user = await get_or_create_user(telegram_id, username, first_name)
    
    # Если заблокирован
    if user.get("is_blocked"):
        await message.answer("⛔ Ваш аккаунт заблокирован администратором.")
        return

    # Динамический текст приветствия с поддержкой кастомизации
    welcome_text = await get_welcome_text(first_name=first_name or "", username=username or "")
    
    await message.answer(
        welcome_text,
        reply_markup=get_client_main_keyboard()
    )
    await message.answer(
        "Или откройте кошелек по ссылке:",
        reply_markup=get_client_inline_keyboard()
    )

@router.message(Command("wallet"))
async def cmd_wallet(message: types.Message):
    p_name = await get_project_name()
    await message.answer(
        f"🚀 <b>Ваш криптокошелек {p_name}:</b>",
        reply_markup=get_client_inline_keyboard()
    )

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    p_name = await get_project_name()
    help_text = (
        f"💡 <b>Справка по использованию {p_name}:</b>\n\n"
        "• Для открытия интерфейса кошелька нажмите кнопку <b>«⚡ Открыть кошелёк»</b> внизу экрана.\n"
        "• В приложении вы можете просматривать балансы, отправлять средства и делать обмен.\n"
        "• Чтобы получить адрес для пополнения любой монеты, выберите монету и нажмите «Получить».\n"
        "• Все операции подтверждаются оператором в течение нескольких минут."
    )
    await message.answer(help_text)
