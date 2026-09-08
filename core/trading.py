import asyncio
import datetime
import logging
from typing import Dict, Any

from core.database import (
    get_active_binary_bets,
    resolve_binary_bet,
    adjust_balance,
    create_transaction
)
from core.rates import get_pair_price
from bot.notifier import notify_client

logger = logging.getLogger("vault.trading")

async def resolve_expired_binary_bets():
    """
    Проверяет и рассчитывает результаты завершившихся бинарных опционов
    """
    try:
        active_bets = await get_active_binary_bets()
        if not active_bets:
            return

        now = datetime.datetime.utcnow()

        for bet in active_bets:
            try:
                expires_at = datetime.datetime.fromisoformat(bet["expires_at"])
                if now < expires_at:
                    continue

                pair = bet["pair"]
                entry_price = bet["entry_price"]
                exit_price = await get_pair_price(pair)
                direction = bet["direction"].upper()
                stake = bet["stake_amount"]
                coin = bet["stake_coin"]
                payout_rate = bet.get("payout_rate", 0.85)

                status = "lost"
                payout_amount = 0.0

                if direction == "CALL":
                    if exit_price > entry_price:
                        status = "won"
                        payout_amount = round(stake + (stake * payout_rate), 4)
                    elif exit_price == entry_price:
                        status = "tie"
                        payout_amount = stake
                elif direction == "PUT":
                    if exit_price < entry_price:
                        status = "won"
                        payout_amount = round(stake + (stake * payout_rate), 4)
                    elif exit_price == entry_price:
                        status = "tie"
                        payout_amount = stake

                # Фиксируем в БД
                await resolve_binary_bet(bet["id"], exit_price, status, payout_amount)

                # Начисляем средства при выигрыше или ничьей
                if payout_amount > 0:
                    comment = f"Выигрыш по опциону #{bet['id']} ({pair} {direction})" if status == "won" else f"Возврат ничьей по опциону #{bet['id']}"
                    await adjust_balance(bet["user_id"], coin, payout_amount, comment=comment)
                    await create_transaction(
                        user_id=bet["user_id"],
                        type_="binary_win" if status == "won" else "binary_refund",
                        coin=coin,
                        amount=payout_amount,
                        status="completed",
                        comment=comment
                    )

                # Отправляем уведомление пользователю в Telegram
                profit_str = f"+{round(payout_amount - stake, 2)} {coin}" if status == "won" else (f"0.00 {coin}" if status == "tie" else f"-{stake} {coin}")
                icon = "🎉" if status == "won" else ("🤝" if status == "tie" else "📉")
                status_title = "ВЫИГРЫШ!" if status == "won" else ("НИЧЬЯ (Возврат)" if status == "tie" else "НЕ СЫГРАЛО")
                dir_icon = "🟢 ВВЕРХ (CALL)" if direction == "CALL" else "🔴 ВНИЗ (PUT)"

                msg = (
                    f"{icon} <b>Бинарный опцион #{bet['id']} — {status_title}</b>\n\n"
                    f"Пара: <b>{pair}</b>\n"
                    f"Прогноз: {dir_icon}\n"
                    f"Цена входа: <code>${entry_price:,.2f}</code>\n"
                    f"Цена закрытия: <code>${exit_price:,.2f}</code>\n"
                    f"Ставка: <b>{stake} {coin}</b>\n"
                    f"Результат: <b>{profit_str}</b>"
                )
                await notify_client(bet["user_id"], msg)
                logger.info(f"Опцион #{bet['id']} рассчитан: {status} (выплата: {payout_amount})")

            except Exception as e:
                logger.error(f"Ошибка расчета опциона #{bet.get('id')}: {e}")

    except Exception as e:
        logger.error(f"Ошибка в resolve_expired_binary_bets: {e}")

async def run_trading_worker():
    """
    Фоновый цикл проверки опционов каждую секунду
    """
    logger.info("Запуск фонового воркера бинарных опционов...")
    while True:
        try:
            await resolve_expired_binary_bets()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Воркер опционов ошибка: {e}")
        await asyncio.sleep(1.0)
