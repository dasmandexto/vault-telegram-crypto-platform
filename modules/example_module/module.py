"""
Example Plug-and-Play Module for Vault.
Demonstrates how easy it is to add API routes, Telegram Bot handlers, and background tasks.
"""
import logging
from typing import Optional, List, Callable, Any
from fastapi import APIRouter
from aiogram import Router, types
from aiogram.filters import Command
from core.modules import BaseModule

logger = logging.getLogger("vault.modules.example")

class ExampleModule(BaseModule):
    name = "demo"
    title = "Demo Extension Module"
    description = "Пример легко подключаемого модуля для добавления нового функционала в Vault"
    version = "1.0.0"
    author = "Vault Developer"
    enabled = True

    def __init__(self):
        super().__init__()
        self.api_router = APIRouter(prefix="/api/modules/demo", tags=["Demo Module"])
        self.bot_router = Router(name="demo_module_router")
        self._setup_routes()
        self._setup_bot()

    def _setup_routes(self):
        @self.api_router.get("/status")
        async def demo_status():
            return {
                "status": "ok",
                "module": self.name,
                "title": self.title,
                "version": self.version,
                "active": True
            }

    def _setup_bot(self):
        @self.bot_router.message(Command("demo"))
        async def cmd_demo(message: types.Message):
            await message.answer(
                f"🧩 <b>Модуль: {self.title}</b> (v{self.version})\n\n"
                f"Статус: <b>Активен ✅</b>\n"
                f"Описание: {self.description}\n\n"
                f"<i>Этот ответ сгенерирован автоматически из подключаемого модуля modules/{self.name}!</i>"
            )

    def get_api_router(self) -> Optional[APIRouter]:
        return self.api_router

    def get_bot_router(self) -> Optional[Router]:
        return self.bot_router

    async def on_startup(self, app, bot=None, dp=None):
        logger.info(f"[{self.name}] Модуль {self.title} успешно запущен.")

    async def on_shutdown(self):
        logger.info(f"[{self.name}] Модуль {self.title} остановлен.")
