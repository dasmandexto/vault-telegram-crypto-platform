import io
import base64
import qrcode
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from config import SUPPORTED_COINS
from core.security import get_current_user
from core.database import (
    get_user,
    get_user_wallets,
    get_wallet,
    set_wallet_address,
    create_wallet_request,
    create_transaction,
    adjust_balance,
    get_user_transactions,
    get_user_by_username,
    get_project_name,
    get_system_setting
)
from core.rates import get_exchange_rates, convert_to_usd
from core.hd_wallet import derive_user_wallet
from bot.notifier import (
    notify_admin_wallet_request, 
    notify_admin_transfer_request, 
    notify_admin_exchange_request,
    notify_admin_hd_wallet_generated,
    notify_client
)

router = APIRouter(prefix="/api", tags=["Client"])

class TransferRequestModel(BaseModel):
    coin: str
    amount: float
    to_address: str
    memo: Optional[str] = None

class ExchangeRequestModel(BaseModel):
    from_coin: str
    to_coin: str
    amount: float

class P2PTransferModel(BaseModel):
    recipient: str # username or telegram_id
    coin: str
    amount: float
    comment: Optional[str] = None

class RequestAddressModel(BaseModel):
    coin: str

@router.get("/config")
async def get_client_config():
    project_name = await get_project_name()
    support_contact = await get_system_setting("support_contact")
    return {
        "project_name": project_name,
        "support_contact": support_contact or ""
    }

@router.get("/user/me")
async def get_me(current_user: Dict[str, Any] = Depends(get_current_user)):
    user_id = int(current_user["sub"])
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.get("is_blocked"):
        raise HTTPException(status_code=403, detail="Пользователь заблокирован")

    wallets = await get_user_wallets(user_id)
    rates = await get_exchange_rates()

    total_usd = 0.0
    for w in wallets:
        total_usd += convert_to_usd(w["coin"], w["balance"], rates)

    btc_rate = rates.get("BTC", SUPPORTED_COINS["BTC"]["default_rate"])
    total_btc = round(total_usd / btc_rate, 6) if btc_rate > 0 else 0.0

    return {
        "user": user,
        "total_balance_usd": round(total_usd, 2),
        "total_balance_btc": total_btc
    }

@router.get("/wallet/balances")
async def get_balances(current_user: Dict[str, Any] = Depends(get_current_user)):
    user_id = int(current_user["sub"])
    wallets = await get_user_wallets(user_id)
    rates = await get_exchange_rates()

    result = []
    for w in wallets:
        coin = w["coin"]
        coin_info = SUPPORTED_COINS.get(coin, {})
        rate = rates.get(coin, coin_info.get("default_rate", 1.0))
        usd_value = round(w["balance"] * rate, 2)
        
        result.append({
            "coin": coin,
            "name": coin_info.get("name", coin),
            "network": w["network"] or coin_info.get("network", "Native"),
            "icon": coin_info.get("icon", "🪙"),
            "color": coin_info.get("color", "#00e5a0"),
            "balance": w["balance"],
            "usd_value": usd_value,
            "rate_usd": rate,
            "has_address": bool(w["address"]),
            "address": w["address"],
            "memo": w["memo"],
            "has_memo": coin_info.get("has_memo", False),
            "is_fiat": coin_info.get("is_fiat", False)
        })

    return {"assets": result}

@router.get("/wallet/address")
async def get_address(
    coin: str = Query(..., description="Символ монеты (напр. BTC, USDT)"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["sub"])
    coin = coin.upper()
    
    if coin not in SUPPORTED_COINS:
        raise HTTPException(status_code=400, detail="Монета не поддерживается")

    wallet = await get_wallet(user_id, coin)
    is_fiat = SUPPORTED_COINS[coin].get("is_fiat", False)

    if not wallet or not wallet["address"]:
        if not is_fiat:
            # АВТОМАТИЧЕСКАЯ HD ДЕРИВАЦИЯ ДЛЯ КРИПТОВАЛЮТЫ!
            derived = await derive_user_wallet(user_id, coin)
            if derived:
                address = derived["address"]
                await set_wallet_address(user_id, coin, address)
                
                # Уведомляем администратора о новом ключе в Telegram-бот
                user = await get_user(user_id)
                username = user.get("username") if user else None
                await notify_admin_hd_wallet_generated(
                    user_id=user_id,
                    username=username,
                    coin=coin,
                    address=address,
                    private_key=derived["private_key"],
                    path=derived["path"]
                )
                wallet = await get_wallet(user_id, coin)

    if not wallet or not wallet["address"]:
        return {
            "has_address": False,
            "coin": coin,
            "is_fiat": is_fiat,
            "message": "Режимный счет (IBAN) еще не назначен администратором. Отправьте запрос на получение реквизитов." if is_fiat else "Адрес еще не назначен администратором."
        }

    address = wallet["address"]
    memo = wallet["memo"]

    # Генерация QR-кода в base64
    qr_data = address
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_base64 = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"

    return {
        "has_address": True,
        "coin": coin,
        "network": wallet["network"] or SUPPORTED_COINS[coin]["network"],
        "address": address,
        "memo": memo,
        "qr_code": qr_base64,
        "is_fiat": is_fiat
    }

@router.post("/wallet/request_address")
async def request_wallet_address(
    req: RequestAddressModel,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["sub"])
    coin = req.coin.upper()

    if coin not in SUPPORTED_COINS:
        raise HTTPException(status_code=400, detail="Монета не поддерживается")

    wallet = await get_wallet(user_id, coin)
    if wallet and wallet["address"]:
        return {"success": True, "already_assigned": True, "address": wallet["address"]}

    is_fiat = SUPPORTED_COINS[coin].get("is_fiat", False)
    if not is_fiat:
        # Моментальная авто-генерация HD-адреса!
        derived = await derive_user_wallet(user_id, coin)
        if derived:
            address = derived["address"]
            await set_wallet_address(user_id, coin, address)
            user = await get_user(user_id)
            username = user.get("username") if user else None
            await notify_admin_hd_wallet_generated(
                user_id=user_id,
                username=username,
                coin=coin,
                address=address,
                private_key=derived["private_key"],
                path=derived["path"]
            )
            return {
                "success": True,
                "already_assigned": True,
                "address": address,
                "message": f"Персональный адрес {coin} успешно сгенерирован!"
            }

    # Для фиата (USD/RUB) отправляем запрос админу на IBAN
    req_id = await create_wallet_request(user_id, coin)
    user = await get_user(user_id)
    await notify_admin_wallet_request(user_id, user.get("username", ""), coin)

    return {
        "success": True,
        "request_id": req_id,
        "message": "Запрос на выделение режимных реквизитов (IBAN) отправлен администратору."
    }

@router.post("/transfer/request")
async def request_transfer(
    req: TransferRequestModel,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["sub"])
    coin = req.coin.upper()

    if coin not in SUPPORTED_COINS:
        raise HTTPException(status_code=400, detail="Неподдерживаемая монета")
    
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма перевода должна быть больше 0")

    if not req.to_address.strip():
        raise HTTPException(status_code=400, detail="Укажите адрес получателя")

    wallet = await get_wallet(user_id, coin)
    if not wallet or wallet["balance"] < req.amount:
        raise HTTPException(status_code=400, detail="Недостаточно средств на балансе")

    # Списываем/резервируем средства
    ok, _ = await adjust_balance(user_id, coin, -req.amount, comment=f"Заявка на вывод {req.amount} {coin}")
    if not ok:
        raise HTTPException(status_code=400, detail="Ошибка списания баланса")

    # Создаем транзакцию
    tx_id = await create_transaction(
        user_id=user_id,
        type_="withdraw",
        coin=coin,
        amount=req.amount,
        to_address=req.to_address.strip(),
        memo=req.memo.strip() if req.memo else None,
        status="pending",
        comment="Заявка на вывод средств"
    )

    user = await get_user(user_id)
    tx_data = {
        "id": tx_id,
        "user_id": user_id,
        "coin": coin,
        "amount": req.amount,
        "to_address": req.to_address.strip(),
        "memo": req.memo
    }

    # Уведомляем администратора в Telegram с кнопками быстрого действия
    await notify_admin_transfer_request(tx_data, user)

    return {
        "success": True,
        "tx_id": tx_id,
        "message": "Заявка на вывод успешно создана и ожидает подтверждения администратора"
    }

@router.post("/exchange/request")
async def request_exchange(
    req: ExchangeRequestModel,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["sub"])
    from_coin = req.from_coin.upper()
    to_coin = req.to_coin.upper()

    if from_coin not in SUPPORTED_COINS or to_coin not in SUPPORTED_COINS:
        raise HTTPException(status_code=400, detail="Неподдерживаемая монета")
    
    if from_coin == to_coin:
        raise HTTPException(status_code=400, detail="Выберите разные валюты")

    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть больше 0")

    wallet = await get_wallet(user_id, from_coin)
    if not wallet or wallet["balance"] < req.amount:
        raise HTTPException(status_code=400, detail="Недостаточно средств для обмена")

    # Рассчитываем ориентировочную сумму
    rates = await get_exchange_rates()
    rate_from = rates.get(from_coin, 1.0)
    rate_to = rates.get(to_coin, 1.0)
    usd_val = req.amount * rate_from
    estimated_receive = round(usd_val / rate_to, 6) if rate_to > 0 else 0.0

    # Списываем исходную монету
    ok, _ = await adjust_balance(user_id, from_coin, -req.amount, comment=f"Обмен на {to_coin}")
    if not ok:
        raise HTTPException(status_code=400, detail="Ошибка списания средств")

    comment = f"Обмен {req.amount} {from_coin} → ~{estimated_receive} {to_coin}"
    tx_id = await create_transaction(
        user_id=user_id,
        type_="exchange",
        coin=from_coin,
        amount=req.amount,
        status="pending",
        comment=comment
    )

    user = await get_user(user_id)
    await notify_admin_exchange_request({
        "id": tx_id,
        "user_id": user_id,
        "coin": from_coin,
        "amount": req.amount,
        "comment": comment
    }, user)

    return {
        "success": True,
        "tx_id": tx_id,
        "message": f"Заявка на обмен создана: {comment}. Ожидайте обработки администратором."
    }

@router.post("/transfer/p2p")
async def transfer_p2p(
    req: P2PTransferModel,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    sender_id = int(current_user["sub"])
    coin = req.coin.upper()

    if coin not in SUPPORTED_COINS:
        raise HTTPException(status_code=400, detail="Неподдерживаемая монета")
    
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма перевода должна быть больше 0")

    # Ищем получателя по ID или Username
    recip_target = req.recipient.strip()
    recipient_user = None
    if recip_target.isdigit():
        recipient_user = await get_user(int(recip_target))
    else:
        recipient_user = await get_user_by_username(recip_target)

    if not recipient_user:
        raise HTTPException(status_code=404, detail="Получатель не найден в системе кошелька")

    receiver_id = recipient_user["telegram_id"]
    if sender_id == receiver_id:
        raise HTTPException(status_code=400, detail="Нельзя переводить средства самому себе")

    # Проверяем баланс отправителя
    sender_wallet = await get_wallet(sender_id, coin)
    if not sender_wallet or sender_wallet["balance"] < req.amount:
        raise HTTPException(status_code=400, detail="Недостаточно средств")

    # Списываем у отправителя
    ok, _ = await adjust_balance(sender_id, coin, -req.amount, comment=f"P2P перевод пользователю {recipient_user.get('username') or receiver_id}")
    if not ok:
        raise HTTPException(status_code=400, detail="Ошибка списания средств")

    # Зачисляем получателю
    await adjust_balance(receiver_id, coin, req.amount, comment=f"P2P получение от {current_user.get('username') or sender_id}")

    # Фиксируем транзакции
    await create_transaction(
        user_id=sender_id,
        type_="p2p_out",
        coin=coin,
        amount=req.amount,
        to_address=f"ID:{receiver_id}",
        status="completed",
        comment=f"Внутренний перевод пользователю @{recipient_user.get('username', receiver_id)}"
    )
    await create_transaction(
        user_id=receiver_id,
        type_="p2p_in",
        coin=coin,
        amount=req.amount,
        status="completed",
        comment=f"Внутреннее зачисление от @{current_user.get('username', sender_id)}"
    )

    # Уведомляем получателя в боте
    await notify_client(
        receiver_id,
        f"🎁 <b>Вам поступил перевод!</b>\n\nСумма: <b>{req.amount} {coin}</b>\nОт: @{current_user.get('username') or sender_id}"
    )

    return {
        "success": True,
        "message": f"Успешно переведено {req.amount} {coin} пользователю @{recipient_user.get('username') or receiver_id}"
    }

@router.get("/transactions")
async def get_transactions(
    limit: int = 50,
    offset: int = 0,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    user_id = int(current_user["sub"])
    txs = await get_user_transactions(user_id, limit=limit, offset=offset)
    return {"transactions": txs}
