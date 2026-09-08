import io
import csv
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query, Response
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from config import SUPPORTED_COINS, settings
from core.security import get_current_admin
from core.database import (
    get_stats,
    get_all_users,
    get_user,
    get_user_wallets,
    get_wallet,
    set_wallet_address,
    adjust_balance,
    set_user_block,
    get_all_transactions,
    get_transaction,
    update_transaction_status,
    create_transaction,
    save_broadcast,
    get_broadcast_history,
    log_admin_action
)
from core.rates import get_exchange_rates, convert_to_usd
from bot.notifier import (
    notify_client,
    notify_client_wallet_assigned,
    notify_client_transfer_status,
    notify_client_balance_adjusted
)
from bot.bot_instance import get_bot

router = APIRouter(prefix="/api/admin", tags=["Admin"])

class WalletUpdateModel(BaseModel):
    coin: str
    address: str
    memo: Optional[str] = None

class BalanceAdjustModel(BaseModel):
    coin: str
    amount: float
    operation: str = "add"  # "add" или "subtract"
    comment: Optional[str] = None

class BlockUserModel(BaseModel):
    blocked: bool

class ApproveTransferModel(BaseModel):
    tx_hash: Optional[str] = None

class RejectTransferModel(BaseModel):
    reason: Optional[str] = "Отклонено администратором"

class ManualTransferModel(BaseModel):
    user_id: int
    coin: str
    amount: float
    direction: str = "in"  # "in" (зачисление) или "out" (списание/вывод)
    to_address: Optional[str] = None
    tx_hash: Optional[str] = None
    comment: Optional[str] = None

class SendMessageModel(BaseModel):
    user_id: int
    text: str

class BroadcastModel(BaseModel):
    message: str
    target: str = "all"  # "all", "active", "positive_balance"

@router.get("/stats")
async def admin_stats(admin: Dict[str, Any] = Depends(get_current_admin)):
    stats = await get_stats()
    return stats

@router.get("/users")
async def admin_users(
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    offset = (page - 1) * limit
    users = await get_all_users(search=search, limit=limit, offset=offset)
    rates = await get_exchange_rates()

    # Считаем суммарный баланс в USD для каждого пользователя
    enhanced_users = []
    for u in users:
        wallets = await get_user_wallets(u["telegram_id"])
        total_usd = 0.0
        coins_with_balance = []
        for w in wallets:
            if w["balance"] > 0:
                coins_with_balance.append(w["coin"])
            total_usd += convert_to_usd(w["coin"], w["balance"], rates)
        
        enhanced_users.append({
            **u,
            "total_balance_usd": round(total_usd, 2),
            "coins": coins_with_balance[:4],
            "wallets_count": len([w for w in wallets if w["address"]])
        })

    return {"users": enhanced_users, "page": page}

@router.get("/users/{user_id}")
async def admin_user_detail(
    user_id: int,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    wallets = await get_user_wallets(user_id)
    rates = await get_exchange_rates()

    total_usd = 0.0
    for w in wallets:
        total_usd += convert_to_usd(w["coin"], w["balance"], rates)

    return {
        "user": user,
        "wallets": wallets,
        "total_balance_usd": round(total_usd, 2)
    }

@router.patch("/users/{user_id}/wallet")
async def admin_set_wallet(
    user_id: int,
    req: WalletUpdateModel,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    coin = req.coin.upper()
    if coin not in SUPPORTED_COINS:
        raise HTTPException(status_code=400, detail="Неподдерживаемая монета")

    await set_wallet_address(user_id, coin, req.address, req.memo)
    await log_admin_action(admin.get("sub"), "set_wallet", f"Адрес {coin} для {user_id}: {req.address}")

    # Уведомляем клиента в Telegram
    await notify_client_wallet_assigned(user_id, coin, req.address, req.memo)

    return {"success": True, "message": f"Адрес {coin} успешно назначен клиенту"}

@router.patch("/users/{user_id}/balance")
async def admin_adjust_balance(
    user_id: int,
    req: BalanceAdjustModel,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    coin = req.coin.upper()
    if coin not in SUPPORTED_COINS:
        raise HTTPException(status_code=400, detail="Неподдерживаемая монета")

    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть положительной")

    delta = req.amount if req.operation == "add" else -req.amount
    comment = req.comment or ("Ручное начисление" if delta > 0 else "Ручное списание")

    ok, new_balance = await adjust_balance(user_id, coin, delta, comment=comment)
    if not ok:
        raise HTTPException(status_code=400, detail="Недостаточно баланса для списания")

    # Создаем запись в транзакциях
    await create_transaction(
        user_id=user_id,
        type_="manual_adjust",
        coin=coin,
        amount=req.amount,
        status="completed",
        comment=f"{comment} ({'+' if delta > 0 else '-'}{req.amount} {coin})"
    )

    await log_admin_action(admin.get("sub"), "adjust_balance", f"{user_id} {coin} {delta}: {comment}")

    # Уведомляем клиента в Telegram
    await notify_client_balance_adjusted(user_id, coin, delta, new_balance, comment)

    return {
        "success": True,
        "new_balance": new_balance,
        "message": f"Баланс {coin} успешно изменен. Новый баланс: {new_balance}"
    }

@router.patch("/users/{user_id}/block")
async def admin_block_user(
    user_id: int,
    req: BlockUserModel,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await set_user_block(user_id, req.blocked)
    action = "block" if req.blocked else "unblock"
    await log_admin_action(admin.get("sub"), action, f"Пользователь {user_id} {action}")

    if req.blocked:
        await notify_client(user_id, "⛔ Ваш аккаунт в Vault был заблокирован администратором.")
    else:
        await notify_client(user_id, "✅ Ваш аккаунт в Vault был разблокирован администратором.")

    return {"success": True, "blocked": req.blocked}

@router.get("/transactions")
async def admin_transactions(
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    offset = (page - 1) * limit
    txs = await get_all_transactions(status=status, limit=limit, offset=offset)
    return {"transactions": txs, "page": page}

@router.post("/transfer/{tx_id}/approve")
async def admin_approve_transfer(
    tx_id: str,
    req: ApproveTransferModel,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    tx = await get_transaction(tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")

    if tx["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Транзакция уже в статусе {tx['status']}")

    await update_transaction_status(tx_id, status="completed", tx_hash=req.tx_hash, comment="Подтверждено администратором")
    await log_admin_action(admin.get("sub"), "approve_transfer", f"Одобрен перевод {tx_id} (hash: {req.tx_hash})")

    # Уведомляем клиента
    await notify_client_transfer_status(
        user_id=tx["user_id"],
        tx_id=tx_id,
        coin=tx["coin"],
        amount=tx["amount"],
        status="completed",
        tx_hash=req.tx_hash
    )

    return {"success": True, "message": f"Транзакция {tx_id} успешно подтверждена"}

@router.post("/transfer/{tx_id}/reject")
async def admin_reject_transfer(
    tx_id: str,
    req: RejectTransferModel,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    tx = await get_transaction(tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")

    if tx["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Транзакция уже в статусе {tx['status']}")

    # Возвращаем средства клиенту, если это был вывод средств
    if tx["type"] in ["withdraw", "exchange"]:
        await adjust_balance(tx["user_id"], tx["coin"], tx["amount"], comment=f"Возврат по заявке {tx_id}")

    await update_transaction_status(tx_id, status="rejected", comment=req.reason)
    await log_admin_action(admin.get("sub"), "reject_transfer", f"Отклонен перевод {tx_id}: {req.reason}")

    # Уведомляем клиента
    await notify_client_transfer_status(
        user_id=tx["user_id"],
        tx_id=tx_id,
        coin=tx["coin"],
        amount=tx["amount"],
        status="rejected",
        reason=req.reason
    )

    return {"success": True, "message": f"Транзакция {tx_id} отклонена, средства возвращены клиенту"}

@router.post("/transfer/manual")
async def admin_manual_transfer(
    req: ManualTransferModel,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    user = await get_user(req.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    coin = req.coin.upper()
    if coin not in SUPPORTED_COINS:
        raise HTTPException(status_code=400, detail="Неподдерживаемая монета")

    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть положительной")

    delta = req.amount if req.direction == "in" else -req.amount
    comment = req.comment or ("Ручное зачисление средств" if delta > 0 else "Ручной вывод средств")

    ok, new_bal = await adjust_balance(req.user_id, coin, delta, comment=comment)
    if not ok:
        raise HTTPException(status_code=400, detail="Недостаточно средств на балансе клиента")

    tx_id = await create_transaction(
        user_id=req.user_id,
        type_="manual_in" if delta > 0 else "manual_out",
        coin=coin,
        amount=req.amount,
        to_address=req.to_address,
        tx_hash=req.tx_hash,
        status="completed",
        comment=comment
    )

    await log_admin_action(admin.get("sub"), "manual_transfer", f"TX {tx_id}: {req.user_id} {delta} {coin}")

    # Уведомляем пользователя
    await notify_client(
        req.user_id,
        f"⚡ <b>Проведена операция администратора</b>\n\n"
        f"Тип: <b>{'Зачисление' if delta > 0 else 'Списание'}</b>\n"
        f"Сумма: <b>{req.amount} {coin}</b>\n"
        f"Новый баланс: <b>{new_bal} {coin}</b>\n"
        f"Комментарий: <i>{comment}</i>"
    )

    return {"success": True, "tx_id": tx_id, "new_balance": new_bal}

@router.post("/message")
async def admin_send_message(
    req: SendMessageModel,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    user = await get_user(req.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    b = get_bot()
    if not b:
        raise HTTPException(status_code=500, detail="Бот не инициализирован")

    try:
        await b.send_message(
            chat_id=req.user_id,
            text=f"💬 <b>Сообщение от поддержки:</b>\n\n{req.text}"
        )
        await log_admin_action(admin.get("sub"), "send_message", f"To {req.user_id}: {req.text[:50]}")
        return {"success": True, "message": "Сообщение доставлено пользователю"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка отправки сообщения: {e}")

@router.post("/broadcast")
async def admin_broadcast(
    req: BroadcastModel,
    admin: Dict[str, Any] = Depends(get_current_admin)
):
    b = get_bot()
    if not b:
        raise HTTPException(status_code=500, detail="Бот не инициализирован")

    users = await get_all_users(limit=10000)
    recipients = []

    for u in users:
        if u.get("is_blocked"):
            continue
        if req.target == "positive_balance" and u.get("total_balance_raw", 0) <= 0:
            continue
        recipients.append(u["telegram_id"])

    sent_count = 0
    for uid in recipients:
        try:
            await b.send_message(
                chat_id=uid,
                text=f"📢 <b>Объявление:</b>\n\n{req.message}"
            )
            sent_count += 1
        except Exception:
            pass

    await save_broadcast(req.message, req.target, sent_count)
    await log_admin_action(admin.get("sub"), "broadcast", f"Отправлено {sent_count} юзерам")

    return {"success": True, "sent_count": sent_count, "total_target": len(recipients)}

@router.get("/broadcast/history")
async def admin_broadcast_history(admin: Dict[str, Any] = Depends(get_current_admin)):
    history = await get_broadcast_history()
    return {"history": history}

@router.get("/export/transactions")
async def export_transactions_csv(admin: Dict[str, Any] = Depends(get_current_admin)):
    txs = await get_all_transactions(limit=10000)
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["TX_ID", "User_ID", "Username", "Type", "Coin", "Amount", "To_Address", "TX_Hash", "Status", "Comment", "Created_At"])
    
    for t in txs:
        writer.writerow([
            t["id"], t["user_id"], t.get("username", ""), t["type"], t["coin"], 
            t["amount"], t.get("to_address", ""), t.get("tx_hash", ""), 
            t["status"], t.get("comment", ""), t["created_at"]
        ])
    
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=transactions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"}
    )

# ── HD MASTER WALLET ENDPOINTS ──
from core.hd_wallet import get_master_info, get_or_create_master_mnemonic, derive_all_user_wallets, derive_user_wallet

class RevealMnemonicModel(BaseModel):
    password: str

@router.get("/hd/info")
async def get_hd_info(admin: Dict[str, Any] = Depends(get_current_admin)):
    info = await get_master_info(mask_mnemonic=True)
    return info

@router.post("/hd/reveal")
async def reveal_hd_mnemonic(req: RevealMnemonicModel, admin: Dict[str, Any] = Depends(get_current_admin)):
    if req.password != settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="Неверный пароль администратора")
    mnemonic = await get_or_create_master_mnemonic()
    await log_admin_action(admin.get("sub"), "reveal_hd_mnemonic", "Просмотр мастер-сид фразы")
    return {"mnemonic": mnemonic}

@router.get("/hd/derive-user")
async def hd_derive_user(user_id: int = Query(...), admin: Dict[str, Any] = Depends(get_current_admin)):
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    wallets = await derive_all_user_wallets(user_id)
    return {
        "user_id": user_id,
        "username": user.get("username"),
        "first_name": user.get("first_name"),
        "wallets": wallets
    }

@router.get("/hd/export-keys")
async def export_hd_keys_csv(admin: Dict[str, Any] = Depends(get_current_admin)):
    users = await get_all_users(limit=1000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["User_ID", "Username", "First_Name", "Coin", "Network", "Address", "Derivation_Path", "Private_Key"])

    for u in users:
        uid = u["telegram_id"]
        wallets = await derive_all_user_wallets(uid)
        for w in wallets:
            writer.writerow([
                uid,
                u.get("username", ""),
                u.get("first_name", ""),
                w["coin"],
                w["network"],
                w["address"],
                w["path"],
                w["private_key"]
            ])

    await log_admin_action(admin.get("sub"), "export_hd_keys", f"Экспорт приватных ключей для {len(users)} пользователей")

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=vault_hd_keys_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"}
    )
