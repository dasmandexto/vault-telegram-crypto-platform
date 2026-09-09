# 🧩 Модульная архитектура Vault

Платформа Vault построена на базе модульной plug-and-play архитектуры. Это позволяет легко расширять функционал (например: стейкинг, P2P-сделки, реферальные программы, новые платежные шлюзы, игры, уведомления), просто добавив папку с модулем в директорию `modules/` — без необходимости изменять ядро приложения.

---

## 📁 Структура каталога модулей

Каждый модуль может быть отдельным файлом `modules/<module_name>.py` или отдельной папкой `modules/<module_name>/`:

```text
modules/
├── __init__.py
├── example_module/
│   ├── __init__.py
│   ├── module.py        # Основной класс модуля, унаследованный от BaseModule
│   ├── handlers.py      # (Опционально) Обработчики бота
│   └── service.py       # (Опционально) Бизнес-логика или работа с БД
```

---

## 🚀 Создание нового модуля за 3 шага

### Шаг 1: Создайте папку модуля
Создайте директорию `modules/my_feature` и файл `modules/my_feature/module.py`.

### Шаг 2: Унаследуйте класс от `BaseModule`
В `modules/my_feature/module.py`:

```python
from core.modules import BaseModule
from fastapi import APIRouter
from aiogram import Router, types
from aiogram.filters import Command

class MyFeatureModule(BaseModule):
    name = "my_feature"                  # Уникальный системный ID
    title = "Мой новый модуль"           # Название для отображения
    description = "Описание возможностей модуля"
    version = "1.0.0"
    author = "Your Name"
    enabled = True                       # Установите False для быстрого отключения

    def __init__(self):
        super().__init__()
        self.api_router = APIRouter(prefix="/api/modules/my-feature", tags=["My Feature"])
        self.bot_router = Router(name="my_feature_bot_router")
        self._setup()

    def _setup(self):
        # 1. Веб-маршруты FastAPI
        @self.api_router.get("/info")
        async def get_info():
            return {"status": "ok", "message": "Привет из нового модуля!"}

        # 2. Команды Telegram-бота
        @self.bot_router.message(Command("myfeature"))
        async def cmd_feature(message: types.Message):
            await message.answer("🎉 Команда нового модуля успешно выполнена!")

    def get_api_router(self):
        return self.api_router

    def get_bot_router(self):
        return self.bot_router

    # (Опционально) Жизненный цикл
    async def on_startup(self, app, bot=None, dp=None):
        print(f"Модуль {self.title} запущен!")

    async def on_shutdown(self):
        print(f"Модуль {self.title} остановлен.")

    # (Опционально) Фоновые задачи
    def get_background_tasks(self):
        return [self._worker]

    async def _worker(self):
        import asyncio
        while True:
            await asyncio.sleep(60)
            # Фоновая логика...
```

### Шаг 3: Перезапустите сервер
`ModuleManager` автоматически обнаружит новый модуль при запуске `run.py`, зарегистрирует все API-маршруты в FastAPI, подключит обработчики бота в Aiogram и запустит фоновые задачи!

---

## 🛠️ Доступные методы `BaseModule`

| Метод / Свойство | Тип | Описание |
|---|---|---|
| `name` | `str` | Уникальный буквенно-цифровой идентификатор модуля |
| `title` | `str` | Человекочитаемое название модуля |
| `enabled` | `bool` | Флаг включения/отключения модуля |
| `get_api_router()` | `APIRouter \| None` | Возвращает роутер FastAPI с эндпоинтами |
| `get_bot_router()` | `Router \| None` | Возвращает роутер Aiogram с обработчиками бота |
| `get_background_tasks()` | `List[Callable]` | Список асинхронных функций для фонового выполнения |
| `on_startup(app, bot, dp)` | `async coroutine` | Хук, вызываемый при старте приложения |
| `on_shutdown()` | `async coroutine` | Хук, вызываемый при остановке приложения |

---

## 🔍 Просмотр подключенных модулей

Все активные модули доступны через эндпоинт:
`GET /api/modules`

И в консоли сервера при старте:
```text
✅ Зарегистрирован модуль: [demo] v1.0.0 — Demo Extension Module
🔗 API роутер модуля [demo] подключен: /api/modules/demo
🤖 Telegram бот роутер модуля [demo] подключен.
```
