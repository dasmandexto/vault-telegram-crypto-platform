import asyncio
import os
import unittest
import tempfile
from config import SUPPORTED_COINS
from core import database
from core.rates import convert_to_usd
from core.security import create_access_token, decode_access_token

class TestVaultCore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Используем временный файл базы данных для тестов
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        database.DB_FILE = self.temp_db.name
        await database.init_db()

    async def asyncTearDown(self):
        try:
            os.remove(self.temp_db.name)
        except OSError:
            pass

    async def test_supported_coins_count(self):
        # Проверяем, что монет ровно 10
        self.assertEqual(len(SUPPORTED_COINS), 10)
        expected_coins = ["BTC", "ETH", "USDT", "TON", "SOL", "BNB", "TRX", "XRP", "DOGE", "USDC"]
        for coin in expected_coins:
            self.assertIn(coin, SUPPORTED_COINS)

    async def test_user_creation_and_wallets(self):
        # Создаем пользователя
        user = await database.get_or_create_user(telegram_id=123456, username="crypto_whale", first_name="Whale")
        self.assertIsNotNone(user)
        self.assertEqual(user["telegram_id"], 123456)
        self.assertEqual(user["username"], "crypto_whale")

        # Проверяем, что для пользователя автоматически созданы кошельки по всем 10 монетам
        wallets = await database.get_user_wallets(telegram_id=123456)
        self.assertEqual(len(wallets), 10)

        coins_in_db = [w["coin"] for w in wallets]
        for coin in SUPPORTED_COINS:
            self.assertIn(coin, coins_in_db)

    async def test_wallet_address_assignment(self):
        user_id = 777
        await database.get_or_create_user(telegram_id=user_id, username="ton_fan")
        
        # Клиент делает запрос на адрес
        req_id = await database.create_wallet_request(user_id=user_id, coin="TON")
        self.assertGreater(req_id, 0)
        
        pending_reqs = await database.get_pending_wallet_requests()
        self.assertTrue(any(r["user_id"] == user_id and r["coin"] == "TON" for r in pending_reqs))

        # Админ присваивает адрес
        test_address = "EQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqB2N"
        test_memo = "1234567"
        await database.set_wallet_address(user_id, "TON", test_address, test_memo)

        # Проверяем обновленный кошелек
        wallet = await database.get_wallet(user_id, "TON")
        self.assertEqual(wallet["address"], test_address)
        self.assertEqual(wallet["memo"], test_memo)

        # Запрос должен закрыться
        pending_after = await database.get_pending_wallet_requests()
        self.assertFalse(any(r["user_id"] == user_id and r["coin"] == "TON" for r in pending_after))

    async def test_balance_adjust_and_limits(self):
        user_id = 888
        await database.get_or_create_user(telegram_id=user_id, username="tester")

        # Зачисление 150 USDT
        ok, new_bal = await database.adjust_balance(user_id, "USDT", 150.0)
        self.assertTrue(ok)
        self.assertEqual(new_bal, 150.0)

        # Списание 50 USDT
        ok, new_bal = await database.adjust_balance(user_id, "USDT", -50.0)
        self.assertTrue(ok)
        self.assertEqual(new_bal, 100.0)

        # Попытка списать больше, чем есть (150 USDT) - должна быть отклонена
        ok, current_bal = await database.adjust_balance(user_id, "USDT", -150.0)
        self.assertFalse(ok)
        self.assertEqual(current_bal, 100.0)

    async def test_transactions_flow(self):
        user_id = 999
        await database.get_or_create_user(telegram_id=user_id)

        tx_id = await database.create_transaction(
            user_id=user_id,
            type_="withdraw",
            coin="BTC",
            amount=0.05,
            to_address="bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
            status="pending"
        )
        self.assertTrue(tx_id.startswith("tx_"))

        tx = await database.get_transaction(tx_id)
        self.assertEqual(tx["status"], "pending")
        self.assertEqual(tx["amount"], 0.05)

        # Одобрение с хэшем
        await database.update_transaction_status(tx_id, "completed", tx_hash="0xabcd1234ef")
        tx_updated = await database.get_transaction(tx_id)
        self.assertEqual(tx_updated["status"], "completed")
        self.assertEqual(tx_updated["tx_hash"], "0xabcd1234ef")

    def test_jwt_tokens(self):
        token = create_access_token({"sub": "12345", "role": "admin"})
        payload = decode_access_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sub"], "12345")
        self.assertEqual(payload["role"], "admin")

    def test_rate_conversion(self):
        rates = {"BTC": 60000.0, "USDT": 1.0, "TON": 6.0}
        self.assertEqual(convert_to_usd("BTC", 0.5, rates), 30000.0)
        self.assertEqual(convert_to_usd("USDT", 250.0, rates), 250.0)
        self.assertEqual(convert_to_usd("TON", 10.0, rates), 60.0)

    async def test_system_settings_and_welcome_template(self):
        # Проверяем значение имени проекта по умолчанию
        p_name = await database.get_project_name()
        self.assertTrue(len(p_name) > 0)

        # Устанавливаем кастомное имя
        await database.set_system_setting("project_name", "SuperVault")
        self.assertEqual(await database.get_project_name(), "SuperVault")

        # Проверяем шаблон приветствия со стандартным текстом
        welcome_default = await database.get_welcome_text(first_name="Алексей", username="alex_crypto")
        self.assertIn("Алексей", welcome_default)
        self.assertIn("SuperVault", welcome_default)

        # Устанавливаем кастомный шаблон приветствия
        custom_tpl = "Привет, {name}! Добро пожаловать в {project_name} (@{username})."
        await database.set_system_setting("welcome_text", custom_tpl)
        welcome_custom = await database.get_welcome_text(first_name="Алексей", username="alex_crypto")
        self.assertEqual(welcome_custom, "Привет, Алексей! Добро пожаловать в SuperVault (@@alex_crypto).")

        # Сбрасываем кастомный шаблон
        await database.delete_system_setting("welcome_text")
        welcome_reset = await database.get_welcome_text(first_name="Алексей", username="alex_crypto")
        self.assertIn("мультивалютный криптокошелек", welcome_reset)

    def test_modular_system_discovery(self):
        from core.modules import ModuleManager, BaseModule
        mgr = ModuleManager(modules_dir="modules")
        mgr.discover_modules()
        
        # Проверяем, что example модуль 'demo' успешно обнаружен и зарегистрирован
        modules_info = mgr.get_all_modules_info()
        mod_names = [m["name"] for m in modules_info]
        self.assertIn("demo", mod_names)
        
        demo_mod = mgr.modules.get("demo")
        self.assertIsNotNone(demo_mod)
        self.assertIsNotNone(demo_mod.get_api_router())
        self.assertIsNotNone(demo_mod.get_bot_router())

if __name__ == "__main__":
    unittest.main()
