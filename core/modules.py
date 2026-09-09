"""
Core Modular System for Vault / Crypto Platform.
Allows easy plug-and-play addition of new features (e.g. Staking, Games, Fiat Gateways, P2P, Notifications).
"""
import os
import sys
import importlib
import inspect
import logging
import asyncio
from typing import List, Optional, Callable, Dict, Any
from fastapi import FastAPI, APIRouter
from aiogram import Dispatcher, Router, Bot

logger = logging.getLogger("vault.modules")


class BaseModule:
    """
    Abstract base class for all Vault modules.
    Subclasses should define module metadata and override hooks as needed.
    """
    name: str = "base_module"
    title: str = "Base Module"
    description: str = ""
    version: str = "1.0.0"
    author: str = "Vault Team"
    enabled: bool = True

    def __init__(self):
        pass

    async def on_startup(self, app: FastAPI, bot: Optional[Bot] = None, dp: Optional[Dispatcher] = None) -> None:
        """Called during application startup."""
        pass

    async def on_shutdown(self) -> None:
        """Called during application shutdown."""
        pass

    def get_api_router(self) -> Optional[APIRouter]:
        """
        Return FastAPI APIRouter to mount under /api or custom prefix.
        """
        return None

    def get_bot_router(self) -> Optional[Router]:
        """
        Return Aiogram Router to include in bot dispatcher.
        """
        return None

    def get_background_tasks(self) -> List[Callable[[], Any]]:
        """
        Return list of async coroutines/functions to run in the background.
        """
        return []

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "enabled": self.enabled
        }


class ModuleManager:
    """
    Manages discovery, loading, lifecycle, and routing of modules.
    """
    def __init__(self, modules_dir: str = "modules"):
        self.modules_dir = modules_dir
        self.modules: Dict[str, BaseModule] = {}
        self.running_tasks: List[asyncio.Task] = []

    def register_module(self, module: BaseModule):
        """Explicitly register an instance of BaseModule."""
        if not module.enabled:
            logger.info(f"Модуль '{module.name}' отключен и пропущен.")
            return
        self.modules[module.name] = module
        logger.info(f"✅ Зарегистрирован модуль: [{module.name}] v{module.version} — {module.title}")

    def discover_modules(self, base_dir: Optional[str] = None):
        """
        Automatically scan modules directory and load all subclasses of BaseModule.
        Supports both:
        - modules/<folder>/module.py or modules/<folder>/__init__.py
        - modules/<name>.py
        """
        target_dir = os.path.join(base_dir or os.getcwd(), self.modules_dir)
        if not os.path.exists(target_dir):
            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception:
                pass
            return

        for item in os.listdir(target_dir):
            if item.startswith("_") or item.startswith("."):
                continue

            item_path = os.path.join(target_dir, item)
            module_import_path = None

            if os.path.isdir(item_path):
                if os.path.exists(os.path.join(item_path, "module.py")):
                    module_import_path = f"{self.modules_dir}.{item}.module"
                elif os.path.exists(os.path.join(item_path, "__init__.py")):
                    module_import_path = f"{self.modules_dir}.{item}"
            elif item.endswith(".py"):
                mod_name = item[:-3]
                module_import_path = f"{self.modules_dir}.{mod_name}"

            if module_import_path:
                try:
                    loaded_py_module = importlib.import_module(module_import_path)
                    for attr_name in dir(loaded_py_module):
                        attr = getattr(loaded_py_module, attr_name)
                        if (
                            inspect.isclass(attr)
                            and issubclass(attr, BaseModule)
                            and attr is not BaseModule
                        ):
                            instance = attr()
                            self.register_module(instance)
                except Exception as e:
                    logger.error(f"❌ Ошибка загрузки модуля {module_import_path}: {e}", exc_info=True)

    def include_api_routers(self, app: FastAPI):
        """Mounts all module API routers to FastAPI."""
        for mod_name, mod in self.modules.items():
            router = mod.get_api_router()
            if router:
                app.include_router(router)
                logger.info(f"🔗 API роутер модуля [{mod_name}] подключен: {router.prefix or ''}")

    def include_bot_routers(self, dp: Dispatcher):
        """Includes all module Aiogram routers to Dispatcher."""
        for mod_name, mod in self.modules.items():
            b_router = mod.get_bot_router()
            if b_router:
                dp.include_router(b_router)
                logger.info(f"🤖 Telegram бот роутер модуля [{mod_name}] подключен.")

    async def start_modules(self, app: FastAPI, bot: Optional[Bot] = None, dp: Optional[Dispatcher] = None):
        """Runs startup hooks and spawns background tasks for all active modules."""
        for mod_name, mod in self.modules.items():
            try:
                await mod.on_startup(app, bot, dp)
            except Exception as e:
                logger.error(f"Ошибка в on_startup модуля [{mod_name}]: {e}")

            for task_coro_fn in mod.get_background_tasks():
                try:
                    t = asyncio.create_task(task_coro_fn())
                    self.running_tasks.append(t)
                except Exception as e:
                    logger.error(f"Ошибка запуска фонового таска в модуле [{mod_name}]: {e}")

    async def stop_modules(self):
        """Stops background tasks and calls on_shutdown hooks."""
        for t in self.running_tasks:
            t.cancel()
        for mod_name, mod in self.modules.items():
            try:
                await mod.on_shutdown()
            except Exception as e:
                logger.error(f"Ошибка в on_shutdown модуля [{mod_name}]: {e}")

    def get_all_modules_info(self) -> List[Dict[str, Any]]:
        return [mod.get_info() for mod in self.modules.values()]


# Global singleton instance
module_manager = ModuleManager()
