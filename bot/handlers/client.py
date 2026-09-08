from aiogram import Router, types
from aiogram.filters import CommandStart, Command
from core.database import get_or_create_user
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

    welcome_text = (
        f"👋 Здравствуйте, <b>{first_name}</b>!\n\n"
        f"Добро пожаловать в мультивалютный криптокошелек <b>Vault</b>.\n\n"
        f"⚡ <b>Доступные возможности:</b>\n"
        f"• Хранение и операции с 10 топ-криптовалютами (BTC, ETH, USDT, TON, SOL, BNB, TRX, XRP, DOGE, USDC)\n"
        f"• Присвоение персональных адресов для пополнения\n"
        f"• Быстрый вывод и переводы средств\n"
        f"• Внутренний обмен валют\n"
        f"• Прозрачная история транзакций\n\n"
        f"Нажмите кнопку ниже, чтобы открыть кошелек 👇"
    )
    
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
    await message.answer(
        "🚀 <b>Ваш криптокошелек Vault:</b>",
        reply_markup=get_client_inline_keyboard()
    )

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        "💡 <b>Справка по использованию Vault:</b>\n\n"
        "• Для открытия интерфейса кошелька нажмите кнопку <b>«⚡ Открыть кошелёк»</b> внизу экрана.\n"
        "• В приложении вы можете просматривать балансы, отправлять средства и делать обмен.\n"
        "• Чтобы получить адрес для пополнения любой монеты, выберите монету и нажмите «Получить».\n"
        "• Все операции подтверждаются оператором в течение нескольких минут."
    )
    await message.answer(help_text)
