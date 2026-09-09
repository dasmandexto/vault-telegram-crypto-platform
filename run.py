import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from aiogram.types import MenuButtonWebApp, WebAppInfo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import settings
from core.database import init_db, get_project_name
from bot.bot_instance import get_bot, dp
from bot.handlers.client import router as client_bot_router
from bot.handlers.admin import router as admin_bot_router
from api.auth import router as auth_api_router
from api.client import router as client_api_router
from api.admin import router as admin_api_router
from api.trading import router as trading_api_router
from core.trading import run_trading_worker
from core.modules import module_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("vault")

bot_task = None
trading_task = None

async def run_bot_polling(b):
    try:
        logger.info("Запуск polling Telegram-бота...")
        await dp.start_polling(b, handle_signals=False)
    except asyncio.CancelledError:
        logger.info("Polling Telegram-бота остановлен.")
    except Exception as e:
        logger.error(f"Ошибка в работе Telegram-бота (polling): {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Инициализация базы данных
    logger.info("Инициализация базы данных SQLite...")
    try:
        await init_db()
        logger.info("База данных готова к работе.")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")

    # 2. Настройка и запуск Telegram-бота
    b = get_bot()
    if b and settings.BOT_TOKEN:
        try:
            # Регистрируем роутеры aiogram
            dp.include_router(client_bot_router)
            dp.include_router(admin_bot_router)
            module_manager.include_bot_routers(dp)

            # Настраиваем Menu Button в Telegram
            if settings.WEBAPP_URL and not settings.WEBAPP_URL.startswith("http://localhost"):
                try:
                    menu_url = f"{settings.WEBAPP_URL}/?v=7" if not settings.WEBAPP_URL.endswith("/") else f"{settings.WEBAPP_URL}?v=7"
                    await b.set_chat_menu_button(
                        menu_button=MenuButtonWebApp(
                            text="⚡ Кошелёк",
                            web_app=WebAppInfo(url=menu_url)
                        )
                    )
                    logger.info(f"Menu Button установлена на {menu_url}")
                except Exception as e:
                    logger.warning(f"Не удалось установить Menu Button: {e}")

            # Запускаем polling в безопасном фоновом таске
            global bot_task
            bot_task = asyncio.create_task(run_bot_polling(b))
            logger.info("Фоновый таск Telegram-бота успешно создан.")
        except Exception as e:
            logger.error(f"Ошибка при настройке бота: {e}")
    else:
        logger.warning("BOT_TOKEN не задан. Бот запущен не будет, работает только Web API.")

    # 3. Фоновый воркер торговли
    global trading_task
    trading_task = asyncio.create_task(run_trading_worker())
    logger.info("Фоновый воркер торгового движка запущен.")

    # 4. Инициализация и запуск активных модулей
    await module_manager.start_modules(app, b, dp)

    yield

    # Завершение работы
    await module_manager.stop_modules()
    if trading_task:
        trading_task.cancel()
        try:
            await trading_task
        except asyncio.CancelledError:
            pass
    if bot_task:
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
    if b:
        try:
            await b.session.close()
        except Exception:
            pass
    logger.info("Сервер остановлен.")

app = FastAPI(title="Vault Crypto WebApp", version="2.0.0", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Запрет кэширования для динамических страниц и скриптов
@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Подключение API роутов
app.include_router(auth_api_router)
app.include_router(client_api_router)
app.include_router(admin_api_router)
app.include_router(trading_api_router)

# Подключение модульных расширений (modules/)
module_manager.discover_modules(BASE_DIR)
module_manager.include_api_routers(app)

@app.get("/api/modules")
async def list_installed_modules():
    return {"modules": module_manager.get_all_modules_info()}

# Статические файлы (абсолютные пути)
client_static_dir = os.path.join(BASE_DIR, "webapp", "client")
admin_static_dir = os.path.join(BASE_DIR, "webapp", "admin")

if os.path.exists(client_static_dir):
    app.mount("/static/client", StaticFiles(directory=client_static_dir), name="client_static")
if os.path.exists(admin_static_dir):
    app.mount("/static/admin", StaticFiles(directory=admin_static_dir), name="admin_static")

# Веб-страницы
@app.get("/")
async def serve_client():
    client_html = os.path.join(client_static_dir, "index.html")
    if os.path.exists(client_html):
        try:
            with open(client_html, "r", encoding="utf-8") as f:
                content = f.read()
            p_name = await get_project_name()
            content = content.replace("<title>Vault — Crypto Wallet</title>", f"<title>{p_name} — Crypto Wallet</title>")
            content = content.replace('<div class="topbar-logo" id="topbar-logo">vault<span>.</span></div>', f'<div class="topbar-logo" id="topbar-logo">{p_name}</div>')
            content = content.replace('<div class="topbar-logo" id="topbar-logo">Vault</div>', f'<div class="topbar-logo" id="topbar-logo">{p_name}</div>')
            return HTMLResponse(content=content, media_type="text/html")
        except Exception:
            return FileResponse(client_html)
    return {"message": "Client WebApp is loading..."}

@app.get("/admin")
async def serve_admin():
    admin_html = os.path.join(admin_static_dir, "index.html")
    if os.path.exists(admin_html):
        try:
            with open(admin_html, "r", encoding="utf-8") as f:
                content = f.read()
            p_name = await get_project_name()
            content = content.replace('<div class="logo" id="admin-logo">vault/admin</div>', f'<div class="logo" id="admin-logo">{p_name}/admin</div>')
            return HTMLResponse(content=content, media_type="text/html")
        except Exception:
            return FileResponse(admin_html)
    return {"message": "Admin Panel is loading..."}

if __name__ == "__main__":
    logger.info(f"Запуск сервера Vault на {settings.HOST}:{settings.PORT}...")
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
