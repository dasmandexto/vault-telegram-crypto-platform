from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from config import settings
from core.security import validate_telegram_init_data, create_access_token
from core.database import get_or_create_user, get_user

router = APIRouter(prefix="/api", tags=["Auth"])

class TelegramAuthRequest(BaseModel):
    init_data: str

class AdminAuthRequest(BaseModel):
    password: Optional[str] = None
    init_data: Optional[str] = None

@router.post("/auth/telegram")
async def auth_telegram(req: TelegramAuthRequest):
    """
    Верификация initData от Telegram WebApp и выдача JWT токена
    """
    user_data = validate_telegram_init_data(req.init_data, settings.BOT_TOKEN)
    
    # В режиме разработки/тестирования, если токен не указан или init_data тестовая
    if not user_data:
        # Попробуем распарсить тестовый запрос, если указан тестовый ID
        if not settings.BOT_TOKEN and req.init_data.startswith("test_"):
            parts = req.init_data.split("_")
            user_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1042391
            user_data = {"id": user_id, "username": "test_user", "first_name": "Test User"}
        else:
            raise HTTPException(status_code=400, detail="Неверные данные авторизации Telegram WebApp")

    telegram_id = user_data["id"]
    username = user_data.get("username", "")
    first_name = user_data.get("first_name", "")

    user = await get_or_create_user(telegram_id, username, first_name)
    if user.get("is_blocked"):
        raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован администратором")

    token = create_access_token({
        "sub": str(telegram_id),
        "username": username,
        "first_name": first_name,
        "role": "user"
    })

    return {
        "success": True,
        "token": token,
        "user": user
    }

@router.post("/admin/auth")
async def auth_admin(req: AdminAuthRequest):
    """
    Авторизация администратора по паролю или через Telegram initData
    """
    is_authorized = False
    admin_id_str = "admin"

    # Вариант 1: По паролю
    if req.password and req.password == settings.ADMIN_PASSWORD:
        is_authorized = True

    # Вариант 2: Через Telegram WebApp initData администратора
    if req.init_data:
        user_data = validate_telegram_init_data(req.init_data, settings.BOT_TOKEN)
        if user_data and user_data["id"] in settings.admin_ids:
            is_authorized = True
            admin_id_str = str(user_data["id"])

    if not is_authorized:
        raise HTTPException(status_code=401, detail="Неверный пароль администратора или нет прав доступа")

    token = create_access_token({
        "sub": admin_id_str,
        "role": "admin"
    })

    return {
        "success": True,
        "token": token,
        "role": "admin"
    }
