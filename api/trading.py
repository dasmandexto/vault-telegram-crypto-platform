from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import datetime

from config import TRADING_PAIRS, BINARY_CONFIG, SUPPORTED_COINS
from core.security import get_current_user, get_current_admin
from core.rates import get_all_pair_prices, get_pair_price, get_chart_data
from core.database import (
    get_wallet,
    adjust_balance,
    create_transaction,
    create_binary_bet,
    get_user_binary_bets,
    get_active_binary_bets,
    get_all_binary_bets,
    get_binary_stats,
    create_spot_order,
    get_user_spot_orders,
    create_futures_position,
    get_user_open_futures,
    get_futures_position,
    close_futures_position,
    get_user_futures_history
)

router = APIRouter(prefix="/api/trading", tags=["Trading"])

class BinaryBetRequest(BaseModel):
    pair: str
    direction: str  # "CALL" или "PUT"
    stake_amount: Optional[float] = None
    stake: Optional[float] = None
    stake_coin: Optional[str] = "USDT"
    duration_seconds: Optional[int] = None
    duration: Optional[int] = None

class SpotTradeRequest(BaseModel):
    pair: str
    side: str  # "BUY" или "SELL"
    amount: float  # Количество базового актива

class FuturesOpenRequest(BaseModel):
    pair: str
    side: str  # "LONG" или "SHORT"
    margin: float  # Сумма маржи в USDT
    leverage: Optional[int] = 10  # 1, 2, 5, 10, 20

class FuturesCloseRequest(BaseModel):
    position_id: int

@router.get("/pairs")
async def get_pairs():
    prices = await get_all_pair_prices()
    result = []
    for p in TRADING_PAIRS:
        pair_name = p["pair"]
        price = prices.get(pair_name, 1.0)
        result.append({
            "pair": pair_name,
            "base": p["base"],
            "quote": p["quote"],
            "price": price,
            "decimals": p.get("decimals", 2),
            "payout_rate": BINARY_CONFIG["default_payout_rate"],
            "expirations": BINARY_CONFIG["expirations"]
        })
    return {"pairs": result}

@router.get("/price")
async def get_price(pair: str = Query("BTC/USDT")):
    price = await get_pair_price(pair)
    return {"pair": pair.upper(), "price": price}

@router.get("/chart")
async def get_chart(
    pair: str = Query("BTC/USDT"),
    timeframe: str = Query("1m"),
    limit: int = Query(40, le=100)
):
    candles = await get_chart_data(pair, timeframe=timeframe, limit=limit)
    return {"pair": pair.upper(), "candles": candles}

@router.post("/binary/bet")
async def place_binary_bet(
    req: BinaryBetRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["sub"])
    pair = req.pair.upper()
    direction = req.direction.upper()
    stake_coin = (req.stake_coin or "USDT").upper()

    stake_amount = req.stake_amount if req.stake_amount is not None else req.stake
    if stake_amount is None or stake_amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма ставки должна быть больше 0")

    duration_seconds = req.duration_seconds if req.duration_seconds is not None else req.duration
    if not duration_seconds or duration_seconds not in BINARY_CONFIG["expirations"]:
        duration_seconds = 30

    if direction not in ["CALL", "PUT"]:
        raise HTTPException(status_code=400, detail="Направление должно быть CALL (Вверх) или PUT (Вниз)")

    if stake_amount < BINARY_CONFIG["min_stake"]:
        raise HTTPException(status_code=400, detail=f"Минимальная ставка: {BINARY_CONFIG['min_stake']} {stake_coin}")

    if stake_coin not in SUPPORTED_COINS:
        raise HTTPException(status_code=400, detail="Валюта ставки не поддерживается")

    # Проверяем баланс пользователя
    wallet = await get_wallet(user_id, stake_coin)
    if not wallet or wallet["balance"] < stake_amount:
        raise HTTPException(status_code=400, detail="Недостаточно средств на балансе для ставки")

    # Списываем сумму ставки
    ok, _ = await adjust_balance(user_id, stake_coin, -stake_amount, comment=f"Ставка на опцион {pair} {direction}")
    if not ok:
        raise HTTPException(status_code=400, detail="Ошибка списания баланса")

    # Фиксируем цену входа
    entry_price = await get_pair_price(pair)
    payout_rate = BINARY_CONFIG["default_payout_rate"]

    bet_id = await create_binary_bet(
        user_id=user_id,
        pair=pair,
        direction=direction,
        stake_amount=stake_amount,
        stake_coin=stake_coin,
        entry_price=entry_price,
        duration_seconds=duration_seconds,
        payout_rate=payout_rate
    )

    await create_transaction(
        user_id=user_id,
        type_="binary_bet",
        coin=stake_coin,
        amount=stake_amount,
        status="completed",
        comment=f"Бинарный опцион #{bet_id}: {pair} {direction} (${entry_price:,.2f})"
    )

    potential_profit = round(stake_amount * payout_rate, 2)

    return {
        "success": True,
        "bet_id": bet_id,
        "pair": pair,
        "direction": direction,
        "entry_price": entry_price,
        "duration_seconds": duration_seconds,
        "stake_amount": stake_amount,
        "stake_coin": stake_coin,
        "potential_profit": potential_profit,
        "message": f"Опцион #{bet_id} успешно открыт по цене ${entry_price:,.2f}!"
    }

@router.get("/binary/active")
async def get_user_active_bets(current_user: Dict[str, Any] = Depends(get_current_user)):
    user_id = int(current_user["sub"])
    all_active = await get_active_binary_bets()
    user_active = [b for b in all_active if b["user_id"] == user_id]
    
    # Добавляем оставшееся время в секундах и алиасы
    now = datetime.datetime.utcnow()
    for b in user_active:
        exp = datetime.datetime.fromisoformat(b["expires_at"])
        remain = max(0, int((exp - now).total_seconds()))
        b["seconds_remaining"] = remain
        b["remaining_seconds"] = remain
        b["potential_payout"] = round(b["stake_amount"] + (b["stake_amount"] * b.get("payout_rate", 0.85)), 2)
        b["strike_price"] = b.get("entry_price", 0.0)
        b["stake"] = b.get("stake_amount", 0.0)
        b["duration"] = b.get("duration_seconds", 30)

    return {"active_bets": user_active, "bets": user_active}

@router.get("/binary/history")
async def get_user_bets_history(
    limit: int = 30,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["sub"])
    bets = await get_user_binary_bets(user_id, limit=limit)
    for b in bets:
        b["strike_price"] = b.get("entry_price", 0.0)
        b["stake"] = b.get("stake_amount", 0.0)
        b["duration"] = b.get("duration_seconds", 30)
        payout = b.get("payout_amount", 0.0)
        stake = b.get("stake_amount", 0.0)
        b["profit"] = round(payout - stake, 2) if b.get("status") == "won" else 0.0
    return {"bets": bets, "history": bets}

@router.post("/spot/market")
async def execute_spot_trade(
    req: SpotTradeRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["sub"])
    pair = req.pair.upper()
    side = req.side.upper()

    if side not in ["BUY", "SELL"]:
        raise HTTPException(status_code=400, detail="Сторона сделки должна быть BUY (Купить) или SELL (Продать)")

    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Количество должно быть больше 0")

    # Ищем пару
    pair_info = next((p for p in TRADING_PAIRS if p["pair"].upper() == pair), None)
    if not pair_info:
        raise HTTPException(status_code=400, detail="Торговая пара не найдена")

    base = pair_info["base"]
    quote = pair_info["quote"]
    price = await get_pair_price(pair)
    total_cost = round(req.amount * price, 4)

    if side == "BUY":
        # Покупка base за quote (нужен баланс quote)
        q_wallet = await get_wallet(user_id, quote)
        if not q_wallet or q_wallet["balance"] < total_cost:
            raise HTTPException(status_code=400, detail=f"Недостаточно {quote} для покупки (требуется {total_cost} {quote})")

        ok1, _ = await adjust_balance(user_id, quote, -total_cost, comment=f"Покупка {req.amount} {base}")
        if not ok1:
            raise HTTPException(status_code=400, detail=f"Ошибка списания {quote}")
        await adjust_balance(user_id, base, req.amount, comment=f"Зачисление {req.amount} {base} по сделке")

        await create_transaction(
            user_id=user_id,
            type_="spot_buy",
            coin=base,
            amount=req.amount,
            status="completed",
            comment=f"Спот покупка: +{req.amount} {base} за {total_cost} {quote} (${price:,.2f})"
        )

    else: # SELL
        # Продажа base за quote (нужен баланс base)
        b_wallet = await get_wallet(user_id, base)
        if not b_wallet or b_wallet["balance"] < req.amount:
            raise HTTPException(status_code=400, detail=f"Недостаточно {base} для продажи")

        ok1, _ = await adjust_balance(user_id, base, -req.amount, comment=f"Продажа {req.amount} {base}")
        if not ok1:
            raise HTTPException(status_code=400, detail=f"Ошибка списания {base}")
        await adjust_balance(user_id, quote, total_cost, comment=f"Зачисление {total_cost} {quote} по сделке")

        await create_transaction(
            user_id=user_id,
            type_="spot_sell",
            coin=base,
            amount=req.amount,
            status="completed",
            comment=f"Спот продажа: -{req.amount} {base} за {total_cost} {quote} (${price:,.2f})"
        )

    order_id = await create_spot_order(user_id, pair, side, price, req.amount, total_cost)

    return {
        "success": True,
        "order_id": order_id,
        "pair": pair,
        "side": side,
        "price": price,
        "amount": req.amount,
        "total": total_cost,
        "message": f"Ордер исполнен: {side} {req.amount} {base} по ${price:,.2f} (Сумма: {total_cost} {quote})"
    }

@router.get("/spot/orders")
async def get_spot_orders(
    limit: int = 30,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["sub"])
    orders = await get_user_spot_orders(user_id, limit=limit)
    return {"orders": orders}

# --- ЭНДПОИНТЫ ФЬЮЧЕРСНОЙ (КОНТРАКТНОЙ) ТОРГОВЛИ ---
@router.post("/futures/open")
async def open_futures_trade(
    req: FuturesOpenRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["sub"])
    pair = req.pair.upper()
    side = req.side.upper()
    leverage = req.leverage if req.leverage in [1, 2, 5, 10, 20] else 10

    if side not in ["LONG", "SHORT"]:
        raise HTTPException(status_code=400, detail="Направление сделки должно быть LONG (Вверх) или SHORT (Вниз)")

    if req.margin <= 0:
        raise HTTPException(status_code=400, detail="Сумма маржи должна быть больше 0")

    # Проверяем торговую пару
    pair_info = next((p for p in TRADING_PAIRS if p["pair"].upper() == pair), None)
    if not pair_info:
        raise HTTPException(status_code=400, detail="Торговая пара не найдена")

    # Проверяем баланс USDT
    u_wallet = await get_wallet(user_id, "USDT")
    if not u_wallet or u_wallet["balance"] < req.margin:
        raise HTTPException(status_code=400, detail=f"Недостаточно USDT для открытия позиции (требуется {req.margin} USDT)")

    # Списываем маржу в USDT
    ok, _ = await adjust_balance(user_id, "USDT", -req.margin, comment=f"Маржа {side} {pair} ({leverage}x)")
    if not ok:
        raise HTTPException(status_code=400, detail="Ошибка списания баланса USDT")

    entry_price = await get_pair_price(pair)
    pos_id = await create_futures_position(
        user_id=user_id,
        pair=pair,
        side=side,
        margin=req.margin,
        leverage=leverage,
        entry_price=entry_price
    )

    await create_transaction(
        user_id=user_id,
        type_="futures_open",
        coin="USDT",
        amount=req.margin,
        status="completed",
        comment=f"Фьючерс #{pos_id}: {side} {pair} {leverage}x (${entry_price:,.2f})"
    )

    return {
        "success": True,
        "position_id": pos_id,
        "pair": pair,
        "side": side,
        "margin": req.margin,
        "leverage": leverage,
        "entry_price": entry_price,
        "message": f"Позиция {side} {pair} ({leverage}x) успешно открыта по цене ${entry_price:,.2f}"
    }

@router.get("/futures/positions")
async def get_futures_positions(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["sub"])
    positions = await get_user_open_futures(user_id)
    
    for pos in positions:
        curr_price = await get_pair_price(pos["pair"])
        pos["current_price"] = curr_price
        entry_p = pos["entry_price"]
        margin = pos["margin"]
        lev = pos["leverage"]

        if pos["side"] == "LONG":
            pnl = (curr_price - entry_p) / entry_p * margin * lev
        else:
            pnl = (entry_p - curr_price) / entry_p * margin * lev

        pos["pnl"] = round(pnl, 2)
        pos["roi"] = round((pnl / margin) * 100, 2)

    return {"positions": positions}

@router.post("/futures/close")
async def close_futures_trade(
    req: FuturesCloseRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["sub"])
    pos = await get_futures_position(req.position_id)
    if not pos or pos["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Позиция не найдена")

    if pos["status"] != "open":
        raise HTTPException(status_code=400, detail="Позиция уже закрыта")

    close_price = await get_pair_price(pos["pair"])
    entry_p = pos["entry_price"]
    margin = pos["margin"]
    lev = pos["leverage"]

    if pos["side"] == "LONG":
        pnl = (close_price - entry_p) / entry_p * margin * lev
    else:
        pnl = (entry_p - close_price) / entry_p * margin * lev

    pnl = round(pnl, 2)
    payout = round(max(0.0, margin + pnl), 2)

    if payout > 0:
        await adjust_balance(user_id, "USDT", payout, comment=f"Закрытие фьючерса #{pos['id']} {pos['pair']} (PnL: {pnl:+.2f} USDT)")

    await close_futures_position(pos["id"], close_price, pnl)

    await create_transaction(
        user_id=user_id,
        type_="futures_close",
        coin="USDT",
        amount=payout,
        status="completed",
        comment=f"Закрытие {pos['side']} {pos['pair']} (PnL: {pnl:+.2f} USDT, Выплата: {payout} USDT)"
    )

    return {
        "success": True,
        "position_id": pos["id"],
        "close_price": close_price,
        "pnl": pnl,
        "payout": payout,
        "message": f"Позиция #{pos['id']} закрыта по ${close_price:,.2f}. PnL: {pnl:+.2f} USDT (Выплата: {payout} USDT)"
    }

@router.get("/futures/history")
async def get_futures_history(
    limit: int = 30,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["sub"])
    history = await get_user_futures_history(user_id, limit=limit)
    return {"history": history}

# --- АДМИН ЭНДПОИНТЫ ТОРГОВЛИ ---
@router.get("/admin/stats")
async def admin_trading_stats(admin: Dict[str, Any] = Depends(get_current_admin)):
    stats = await get_binary_stats()
    return stats

@router.get("/admin/bets")
async def admin_trading_bets(
    limit: int = 50,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    bets = await get_all_binary_bets(limit=limit)
    return {"bets": bets}
