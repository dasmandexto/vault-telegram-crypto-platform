import hmac
import hashlib
import json
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import jwt
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import settings

ALGORITHM = "HS256"
security_scheme = HTTPBearer(auto_error=False)

def validate_telegram_init_data(init_data: str, bot_token: str) -> Optional[Dict[str, Any]]:
    """
    Валидация строки initData от Telegram WebApp по официальному алгоритму HMAC-SHA256.
    """
    if not init_data or not bot_token:
        return None

    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed_data:
            return None
        
        received_hash = parsed_data.pop("hash")
        
        # Сортируем пары key=value по алфавиту
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        
        # Секретный ключ = HMAC_SHA256("WebAppData", bot_token)
        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        
        # Вычисляем хеш
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        
        if hmac.compare_digest(calculated_hash, received_hash):
            user_data = parsed_data.get("user")
            if user_data:
                return json.loads(user_data)
        return None
    except Exception:
        return None

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=7)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except Exception:
        return None

async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme)) -> Dict[str, Any]:
    if not credentials:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Недействительный или истекший токен")
    
    return payload

async def get_current_admin(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme)) -> Dict[str, Any]:
    user = await get_current_user(credentials)
    role = user.get("role")
    sub = user.get("sub")

    # Проверяем, является ли админом по роли или по Telegram ID
    is_admin = False
    if role == "admin":
        is_admin = True
    elif str(sub).isdigit() and int(sub) in settings.admin_ids:
        is_admin = True

    if not is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещен: требуются права администратора")

    return user
