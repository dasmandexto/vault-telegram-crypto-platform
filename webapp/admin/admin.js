// Vault Admin Panel Logic
let adminToken = localStorage.getItem("vault_admin_token") || "";
let selectedUserId = null;
let selectedUserObj = null;

const tg = window.Telegram?.WebApp;
if (tg) {
  tg.expand();
}

async function adminApi(url, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(adminToken ? { "Authorization": `Bearer ${adminToken}` } : {}),
    ...(options.headers || {})
  };

  const resp = await fetch(url, { ...options, headers });
  if (resp.status === 401 || resp.status === 403) {
    localStorage.removeItem("vault_admin_token");
    adminToken = "";
    openModal('login');
    throw new Error("Не авторизован");
  }
  return resp.json();
}

async function loadAdminBranding() {
  try {
    const res = await fetch("/api/config");
    if (res.ok) {
      const cfg = await res.json();
      if (cfg.project_name) {
        document.title = `Admin Panel — ${cfg.project_name}`;
        const logo = document.getElementById("admin-logo");
        if (logo) logo.textContent = `${cfg.project_name}/admin`;
      }
    }
  } catch (e) {}
}

async function initAdmin() {
  await loadAdminBranding();
  // Пытаемся автоматически авторизоваться через Telegram initData, если открыто внутри Telegram
  if (!adminToken && tg?.initData) {
    try {
      const authRes = await fetch("/api/admin/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: tg.initData })
      });
      const data = await authRes.json();
      if (data.token) {
        adminToken = data.token;
        localStorage.setItem("vault_admin_token", adminToken);
      }
    } catch (e) {}
  }

  if (!adminToken) {
    openModal('login');
    return;
  }

  closeModal('login');
  await loadDashboard();
}

async function submitLogin() {
  const pwd = document.getElementById("login-password").value.trim();
  if (!pwd) return;

  try {
    const res = await fetch("/api/admin/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pwd })
    });
    const data = await res.json();
    if (data.token) {
      adminToken = data.token;
      localStorage.setItem("vault_admin_token", adminToken);
      closeModal('login');
      await loadDashboard();
    } else {
      alert(data.detail || "Неверный пароль");
    }
  } catch (e) {
    alert("Ошибка авторизации: " + e.message);
  }
}

// ── DASHBOARD ──
async function loadDashboard() {
  try {
    const stats = await adminApi("/api/admin/stats");
    document.getElementById("stat-users").textContent = stats.users_total;
    document.getElementById("stat-pending").textContent = stats.pending_tx;
    document.getElementById("stat-vol").textContent = `$${stats.volume_24h}`;
    document.getElementById("stat-blocked").textContent = stats.blocked_users;
    document.getElementById("hdr-pending-num").textContent = stats.pending_tx;

    const navBadge = document.getElementById("nav-pending-badge");
    if (navBadge) {
      navBadge.textContent = stats.pending_tx;
      navBadge.style.display = stats.pending_tx > 0 ? "flex" : "none";
    }

    await loadPendingTransfers();
  } catch (e) {
    console.error("Dashboard stats error:", e);
  }
}

async function loadPendingTransfers() {
  const container = document.getElementById("dash-pending-list");
  try {
    const data = await adminApi("/api/admin/transactions?status=pending");
    container.innerHTML = "";

    if (!data.transactions || data.transactions.length === 0) {
      container.innerHTML = `<div style="text-align:center; padding:24px; color:var(--muted); font-size:13px;">Нет заявок, ожидающих обработки</div>`;
      return;
    }

    data.transactions.forEach(tx => {
      const card = `
        <div class="pending-card">
          <div class="pc-top">
            <div class="pc-user">
              <div class="pc-avatar">👤</div>
              <div>
                <div class="pc-name">@${tx.username || 'user'}</div>
                <div class="pc-id">ID: ${tx.user_id}</div>
              </div>
            </div>
            <div class="pc-amount">
              <div class="pc-amt-val">${tx.amount}</div>
              <div class="pc-amt-coin">${tx.coin}</div>
            </div>
          </div>
          <div class="pc-time">📅 ${new Date(tx.created_at).toLocaleString("ru-RU")} · #${tx.id}</div>
          <div class="pc-addr">→ ${tx.to_address || tx.comment || 'Заявка на операцию'} ${tx.memo ? '(Memo: ' + tx.memo + ')' : ''}</div>
          <div class="pc-actions">
            <button class="pc-btn approve" onclick="approveTransfer('${tx.id}')">✓ Подтвердить</button>
            <button class="pc-btn reject" onclick="rejectTransfer('${tx.id}')">✕ Отклонить</button>
          </div>
        </div>
      `;
      container.insertAdjacentHTML("beforeend", card);
    });
  } catch (e) {
    console.error("Load pending error:", e);
  }
}

async function approveTransfer(id) {
  const hash = prompt(`Введите TX Hash транзакции в блокчейне (необязательно):`);
  try {
    const res = await adminApi(`/api/admin/transfer/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ tx_hash: hash })
    });
    alert(res.message || "Перевод подтвержден!");
    await loadDashboard();
    if (document.getElementById("page-all-tx").classList.contains("active")) {
      await loadAllTransactions();
    }
  } catch (e) {
    alert("Ошибка: " + e.message);
  }
}

async function rejectTransfer(id) {
  const reason = prompt("Укажите причину отклонения (будет отправлена клиенту):");
  if (reason === null) return;

  try {
    const res = await adminApi(`/api/admin/transfer/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason: reason || "Отклонено оператором" })
    });
    alert(res.message || "Перевод отклонен!");
    await loadDashboard();
    if (document.getElementById("page-all-tx").classList.contains("active")) {
      await loadAllTransactions();
    }
  } catch (e) {
    alert("Ошибка: " + e.message);
  }
}

// ── USERS ──
let searchTimeout = null;
function debounceUserSearch() {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(loadUsers, 300);
}

async function loadUsers() {
  const q = document.getElementById("user-search-input").value.trim();
  const container = document.getElementById("admin-users-list");
  container.innerHTML = `<div style="text-align:center; padding:16px; color:var(--muted)">Загрузка пользователей...</div>`;

  try {
    const data = await adminApi(`/api/admin/users?search=${encodeURIComponent(q)}`);
    container.innerHTML = "";

    if (!data.users || data.users.length === 0) {
      container.innerHTML = `<div style="text-align:center; padding:24px; color:var(--muted)">Пользователи не найдены</div>`;
      return;
    }

    data.users.forEach(u => {
      const isBlocked = u.is_blocked;
      const avatarIcon = isBlocked ? "🔴" : "👤";
      const meta = isBlocked ? "заблокирован" : `${u.wallets_count} кошельков`;
      const coinsStr = u.coins.length > 0 ? u.coins.join(" · ") : "нет баланса";

      const item = `
        <div class="user-item" onclick="openUserDetail('${u.telegram_id}')">
          <div class="u-avatar">${avatarIcon}</div>
          <div class="u-info">
            <div class="u-name">${u.first_name || ''} (@${u.username || 'без username'})</div>
            <div class="u-meta">ID: ${u.telegram_id} · ${meta}</div>
          </div>
          <div class="u-right">
            <div class="u-balance" style="${isBlocked ? 'color:var(--red)' : ''}">$${u.total_balance_usd.toFixed(2)}</div>
            <div class="u-wallets">${coinsStr}</div>
          </div>
        </div>
      `;
      container.insertAdjacentHTML("beforeend", item);
    });
  } catch (e) {
    console.error("Load users error:", e);
  }
}

async function openUserDetail(id) {
  selectedUserId = id;
  try {
    const data = await adminApi(`/api/admin/users/${id}`);
    selectedUserObj = data;

    const u = data.user;
    document.getElementById("ud-name").textContent = `${u.first_name || ''} (@${u.username || 'none'})`;
    document.getElementById("ud-id").textContent = `ID: ${u.telegram_id} · Баланс: $${data.total_balance_usd.toFixed(2)}`;
    
    const blockBtn = document.getElementById("btn-block-toggle");
    if (u.is_blocked) {
      blockBtn.innerHTML = `<span class="ag-icon">🔓</span> Разблокировать`;
      blockBtn.className = "ag-btn green";
    } else {
      blockBtn.innerHTML = `<span class="ag-icon">🚫</span> Заблокировать`;
      blockBtn.className = "ag-btn red";
    }

    const bList = document.getElementById("ud-balances-list");
    bList.innerHTML = "";

    data.wallets.forEach(w => {
      const addrStr = w.address ? `${w.address.slice(0, 10)}...${w.address.slice(-6)}` : `<span style="color:var(--warn)">не задан</span>`;
      const memoStr = w.memo ? ` (Memo: ${w.memo})` : '';
      const row = `
        <div class="info-row">
          <span class="key">${w.coin} (${w.network})</span>
          <span class="val">${w.balance} [${addrStr}${memoStr}]</span>
        </div>
      `;
      bList.insertAdjacentHTML("beforeend", row);
    });

    openModal('user-detail');
  } catch (e) {
    alert("Ошибка загрузки пользователя: " + e.message);
  }
}

async function toggleBlockUser() {
  if (!selectedUserObj) return;
  const newBlocked = !selectedUserObj.user.is_blocked;
  const actionName = newBlocked ? "заблокировать" : "разблокировать";

  if (!confirm(`Вы уверены, что хотите ${actionName} пользователя?`)) return;

  try {
    await adminApi(`/api/admin/users/${selectedUserId}/block`, {
      method: "PATCH",
      body: JSON.stringify({ blocked: newBlocked })
    });
    alert(`Пользователь успешно ${newBlocked ? 'заблокирован' : 'разблокирован'}!`);
    await openUserDetail(selectedUserId);
    await loadUsers();
    await loadDashboard();
  } catch (e) {
    alert("Ошибка: " + e.message);
  }
}

// ── SET WALLET MODAL ──
function openSetWalletModal() {
  updateSwCoinLabels();
  openModal('set-wallet');
}

function updateSwCoinLabels() {
  const coin = document.getElementById("sw-coin").value;
  const isFiat = coin === "USD" || coin === "RUB";
  const addrLbl = document.getElementById("sw-address-lbl");
  const addrInp = document.getElementById("sw-address");
  const memoLbl = document.getElementById("sw-memo-lbl");
  const memoInp = document.getElementById("sw-memo");

  if (isFiat) {
    if (addrLbl) addrLbl.textContent = `Режимный IBAN / Счет (${coin})`;
    if (addrInp) addrInp.placeholder = coin === "USD" ? "IBAN (напр. GE29NB... / BY04...)" : "Счет / Карта (напр. 40817810... / 2200...)";
    if (memoLbl) memoLbl.textContent = "Банк / Получатель / БИК (опционально)";
    if (memoInp) memoInp.placeholder = "Банк, БИК, ФИО или Назначение перевода";
  } else {
    if (addrLbl) addrLbl.textContent = `Адрес кошелька (${coin})`;
    if (addrInp) addrInp.placeholder = "Адрес блокчейн кошелька";
    if (memoLbl) memoLbl.textContent = "Memo / Destination Tag (опционально)";
    if (memoInp) memoInp.placeholder = "Цифровой тэг для XRP / TON";
  }
}

async function submitSetWallet() {
  if (!selectedUserId) return;
  const coin = document.getElementById("sw-coin").value;
  const address = document.getElementById("sw-address").value.trim();
  const memo = document.getElementById("sw-memo").value.trim();

  if (!address) {
    alert("Введите адрес кошелька");
    return;
  }

  try {
    const res = await adminApi(`/api/admin/users/${selectedUserId}/wallet`, {
      method: "PATCH",
      body: JSON.stringify({ coin, address, memo })
    });
    alert(res.message || "Адрес успешно сохранен!");
    closeModal('set-wallet');
    await openUserDetail(selectedUserId);
    await loadDashboard();
  } catch (e) {
    alert("Ошибка: " + e.message);
  }
}

// ── ADJUST BALANCE MODAL ──
async function submitAdjustBalance() {
  if (!selectedUserId) return;
  const coin = document.getElementById("ab-coin").value;
  const operation = document.getElementById("ab-operation").value;
  const amount = parseFloat(document.getElementById("ab-amount").value);
  const comment = document.getElementById("ab-comment").value.trim();

  if (isNaN(amount) || amount <= 0) {
    alert("Введите корректную сумму");
    return;
  }

  try {
    const res = await adminApi(`/api/admin/users/${selectedUserId}/balance`, {
      method: "PATCH",
      body: JSON.stringify({ coin, amount, operation, comment })
    });
    alert(res.message || "Баланс успешно обновлен!");
    closeModal('adjust-balance');
    await openUserDetail(selectedUserId);
  } catch (e) {
    alert("Ошибка: " + e.message);
  }
}

// ── MANUAL TX MODAL ──
async function submitManualTx() {
  if (!selectedUserId) return;
  const direction = document.getElementById("mt-direction").value;
  const coin = document.getElementById("mt-coin").value;
  const amount = parseFloat(document.getElementById("mt-amount").value);
  const to_address = document.getElementById("mt-to").value.trim();
  const tx_hash = document.getElementById("mt-hash").value.trim();

  if (isNaN(amount) || amount <= 0) {
    alert("Введите корректную сумму");
    return;
  }

  try {
    const res = await adminApi("/api/admin/transfer/manual", {
      method: "POST",
      body: JSON.stringify({
        user_id: parseInt(selectedUserId),
        coin,
        amount,
        direction,
        to_address,
        tx_hash
      })
    });
    alert("Перевод успешно проведен!");
    closeModal('manual-tx');
    await openUserDetail(selectedUserId);
  } catch (e) {
    alert("Ошибка: " + e.message);
  }
}

// ── SEND MESSAGE MODAL ──
async function submitSendMessage() {
  if (!selectedUserId) return;
  const text = document.getElementById("sm-text").value.trim();
  if (!text) return;

  try {
    const res = await adminApi("/api/admin/message", {
      method: "POST",
      body: JSON.stringify({ user_id: parseInt(selectedUserId), text })
    });
    alert(res.message || "Сообщение отправлено!");
    closeModal('send-msg');
  } catch (e) {
    alert("Ошибка: " + e.message);
  }
}

// ── ALL TRANSACTIONS ──
let currentTxFilter = "";
async function filterTransactions(status) {
  currentTxFilter = status;
  await loadAllTransactions();
}

async function loadAllTransactions() {
  const container = document.getElementById("admin-all-tx-list");
  container.innerHTML = `<div style="text-align:center; padding:16px; color:var(--muted)">Загрузка транзакций...</div>`;

  try {
    const url = `/api/admin/transactions?status=${encodeURIComponent(currentTxFilter)}`;
    const data = await adminApi(url);
    container.innerHTML = "";

    if (!data.transactions || data.transactions.length === 0) {
      container.innerHTML = `<div style="text-align:center; padding:24px; color:var(--muted)">Транзакции не найдены</div>`;
      return;
    }

    data.transactions.forEach(tx => {
      const item = `
        <div class="tx-admin">
          <div class="tx-dot ${tx.status}"></div>
          <div class="tx-admin-info">
            <div class="tx-admin-name">@${tx.username || tx.user_id} · ${tx.comment || tx.type}</div>
            <div class="tx-admin-meta">#${tx.id} · ${new Date(tx.created_at).toLocaleTimeString("ru-RU")} · ${tx.status}</div>
          </div>
          <div class="tx-admin-amount" style="color:${tx.status === 'completed' ? 'var(--green)' : (tx.status === 'rejected' ? 'var(--red)' : 'var(--accent)')}">
            ${tx.amount} ${tx.coin}
          </div>
        </div>
      `;
      container.insertAdjacentHTML("beforeend", item);
    });
  } catch (e) {
    console.error("Load all tx error:", e);
  }
}

// ── BROADCAST ──
async function sendBroadcast() {
  const target = document.getElementById("bcast-target").value;
  const message = document.getElementById("bcast-text").value.trim();

  if (!message) {
    alert("Введите текст сообщения для рассылки");
    return;
  }

  if (!confirm(`Отправить рассылку выбранной аудитории?`)) return;

  try {
    const res = await adminApi("/api/admin/broadcast", {
      method: "POST",
      body: JSON.stringify({ message, target })
    });
    alert(`Рассылка завершена! Отправлено: ${res.sent_count} пользователям.`);
    document.getElementById("bcast-text").value = "";
    await loadBroadcastHistory();
  } catch (e) {
    alert("Ошибка: " + e.message);
  }
}

async function loadBroadcastHistory() {
  const container = document.getElementById("bcast-history-list");
  try {
    const data = await adminApi("/api/admin/broadcast/history");
    container.innerHTML = "";

    if (!data.history || data.history.length === 0) {
      container.innerHTML = `<div style="text-align:center; padding:16px; color:var(--muted)">Рассылок еще не было</div>`;
      return;
    }

    data.history.forEach(h => {
      const row = `
        <div class="tx-admin">
          <div class="tx-dot completed"></div>
          <div class="tx-admin-info">
            <div class="tx-admin-name">${h.message.slice(0, 40)}...</div>
            <div class="tx-admin-meta">${new Date(h.sent_at).toLocaleDateString("ru-RU")} · Получателей: ${h.recipients_count} (${h.target})</div>
          </div>
        </div>
      `;
      container.insertAdjacentHTML("beforeend", row);
    });
  } catch (e) {
    console.error("Load broadcast history error:", e);
  }
}

// ── EXPORT CSV ──
function exportTxCsv() {
  window.open(`/api/admin/export/transactions?token=${adminToken}`, "_blank");
}
function exportUsersCsv() {
  alert("Экспорт списка пользователей формируется в CSV...");
}

function copyAdminText(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    if (btn) {
      const orig = btn.textContent;
      btn.textContent = "Скопировано! ✓";
      setTimeout(() => { btn.textContent = orig; }, 1500);
    } else {
      alert("Скопировано в буфер обмена!");
    }
  }).catch(() => {
    prompt("Скопируйте вручную:", text);
  });
}

// ── HD MASTER WALLET LOGIC ──
async function loadHdInfo() {
  try {
    const data = await adminApi("/api/admin/hd/info");
    document.getElementById("hd-fingerprint").textContent = `ID: ${data.fingerprint}`;
    document.getElementById("hd-mnemonic-display").textContent = data.mnemonic;
  } catch (e) {
    console.error("Load HD info error:", e);
  }
}

async function revealMasterMnemonic() {
  const pwd = prompt("Введите пароль администратора для открытия мастер-сид фразы:");
  if (!pwd) return;

  try {
    const res = await adminApi("/api/admin/hd/reveal", {
      method: "POST",
      body: JSON.stringify({ password: pwd })
    });
    if (res.mnemonic) {
      document.getElementById("hd-mnemonic-display").innerHTML = `
        <div style="background:rgba(255,77,106,0.1); border:1px solid var(--red); padding:10px; border-radius:8px; margin-bottom:10px; color:var(--red); font-size:11px;">
          ⚠️ ВНИМАНИЕ: Никому не передавайте эти слова! Тот, кто владеет сид-фразой, владеет всеми средствами сервиса.
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
          <span style="font-size:11px; color:var(--muted)">24 слова BIP-39:</span>
          <button class="section-action" onclick="copyAdminText('${res.mnemonic.replace(/'/g, "\\'")}', this)" style="padding:3px 10px; font-size:11px; border-color:var(--accent); color:var(--accent);">Копировать 📋</button>
        </div>
        <div style="color:var(--accent); font-weight:700; user-select:all; cursor:text; font-size:13px; line-height:1.6; background:rgba(0,0,0,0.5); padding:12px; border-radius:8px; border:1px solid rgba(240,180,41,0.3);">${res.mnemonic}</div>
      `;
      document.getElementById("hd-reveal-btn").style.display = "none";
    }
  } catch (e) {
    alert("Ошибка: " + e.message);
  }
}

async function inspectUserHdKeys() {
  const uid = document.getElementById("hd-user-input").value.trim();
  const container = document.getElementById("hd-user-keys-result");
  if (!uid) {
    alert("Введите Telegram ID пользователя");
    return;
  }

  container.innerHTML = `<div style="text-align:center; padding:12px; color:var(--muted)">Расчет блокчейн-деривации...</div>`;

  try {
    const data = await adminApi(`/api/admin/hd/derive-user?user_id=${uid}`);
    if (!data.wallets || data.wallets.length === 0) {
      container.innerHTML = `<div style="color:var(--red); padding:12px;">Кошельки не найдены</div>`;
      return;
    }

    let html = `
      <div style="background:var(--surface2); border-radius:10px; padding:12px; margin-bottom:12px;">
        <div style="font-weight:700; font-size:13px; color:var(--accent); margin-bottom:4px;">Пользователь: @${data.username || 'без username'} (ID: ${data.user_id})</div>
        <div style="font-size:11px; color:var(--muted)">Всего деривировано кошельков: ${data.wallets.length}</div>
      </div>
      <div style="display:flex; flex-direction:column; gap:8px;">
    `;

    data.wallets.forEach(w => {
      html += `
        <div style="background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:10px 12px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span style="font-weight:700; font-size:13px; color:#fff;">${w.coin} <span style="font-size:10px; color:var(--muted)">(${w.network})</span></span>
            <span style="font-family:'IBM Plex Mono', monospace; font-size:10px; color:var(--muted)">${w.path}</span>
          </div>
          <div style="font-size:11px; color:var(--accent); word-break:break-all; font-family:'IBM Plex Mono', monospace; margin-bottom:6px; display:flex; justify-content:space-between; align-items:center; gap:6px;">
            <span style="user-select:all;">📫 ${w.address}</span>
            <button class="section-action" onclick="copyAdminText('${w.address}', this)" style="padding:2px 6px; font-size:10px; flex-shrink:0;">копия</button>
          </div>
          <div style="font-size:10px; color:var(--muted); background:rgba(0,0,0,0.3); padding:6px 8px; border-radius:6px; font-family:'IBM Plex Mono', monospace; word-break:break-all;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:2px;">
              <span>🔑 <b>PrivKey:</b></span>
              <button class="section-action" onclick="copyAdminText('${w.private_key}', this)" style="padding:1px 6px; font-size:9px; color:var(--accent); border-color:rgba(240,180,41,0.4);">копировать ключ 📋</button>
            </div>
            <div style="color:#fff; user-select:all;">${w.private_key}</div>
          </div>
        </div>
      `;
    });

    html += `</div>`;
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<div style="color:var(--red); padding:12px;">Ошибка: ${e.message}</div>`;
  }
}

async function openUserKeysFromDetail() {
  if (!selectedUserId) return;
  const mukContent = document.getElementById("muk-content");
  const userName = selectedUserObj?.user?.username ? `@${selectedUserObj.user.username}` : `ID ${selectedUserId}`;
  document.getElementById("muk-title").textContent = `🔐 Ключи: ${userName}`;
  mukContent.innerHTML = `<div style="text-align:center; padding:24px; color:var(--muted)">Генерация блокчейн-ключей...</div>`;
  openModal('user-keys');

  try {
    const data = await adminApi(`/api/admin/hd/derive-user?user_id=${selectedUserId}`);
    if (!data.wallets || data.wallets.length === 0) {
      mukContent.innerHTML = `<div style="color:var(--red); padding:16px;">Кошельки не найдены</div>`;
      return;
    }

    let html = `
      <div style="background:rgba(240,180,41,0.1); border:1px solid rgba(240,180,41,0.3); border-radius:8px; padding:10px; font-size:11px; color:var(--accent); margin-bottom:8px;">
        💡 <b>Прямой доступ:</b> Этот приватный ключ можно импортировать в любой официальный кошелек (Electrum, TrustWallet, MetaMask, TronLink) и вывести монеты без участия пользователя.
      </div>
    `;

    data.wallets.forEach(w => {
      html += `
        <div style="background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:10px 12px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <span style="font-weight:700; font-size:13px; color:#fff;">${w.coin} <span style="font-size:10px; color:var(--muted)">(${w.network})</span></span>
            <span style="font-family:'IBM Plex Mono', monospace; font-size:10px; color:var(--muted)">${w.path}</span>
          </div>
          <div style="font-size:11px; color:var(--accent); word-break:break-all; font-family:'IBM Plex Mono', monospace; margin-bottom:6px; display:flex; justify-content:space-between; align-items:center; gap:6px;">
            <span style="user-select:all;">📫 ${w.address}</span>
            <button class="section-action" onclick="copyAdminText('${w.address}', this)" style="padding:2px 6px; font-size:10px; flex-shrink:0;">копия</button>
          </div>
          <div style="font-size:10px; color:var(--muted); background:rgba(0,0,0,0.4); padding:6px 8px; border-radius:6px; font-family:'IBM Plex Mono', monospace; word-break:break-all;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:2px;">
              <span>🔑 <b>Private Key:</b></span>
              <button class="section-action" onclick="copyAdminText('${w.private_key}', this)" style="padding:1px 6px; font-size:9px; color:var(--accent); border-color:rgba(240,180,41,0.4);">копировать ключ 📋</button>
            </div>
            <div style="color:#fff; user-select:all; margin-top:2px;">${w.private_key}</div>
          </div>
        </div>
      `;
    });

    mukContent.innerHTML = html;
  } catch (e) {
    mukContent.innerHTML = `<div style="color:var(--red); padding:16px;">Ошибка: ${e.message}</div>`;
  }
}

function exportHdKeysCsv() {
  window.open(`/api/admin/hd/export-keys?token=${adminToken}`, "_blank");
}

// ── SETTINGS ──
async function loadSettings() {
  try {
    const data = await adminApi("/api/admin/settings");
    const pNameInput = document.getElementById("settings-project-name");
    const supportInput = document.getElementById("settings-support-contact");
    const welcomeInput = document.getElementById("settings-welcome-text");

    if (pNameInput) pNameInput.value = data.project_name || "";
    if (supportInput) supportInput.value = data.support_contact || "";
    if (welcomeInput) welcomeInput.value = data.welcome_text || "";

    updateWelcomePreview();
  } catch (e) {
    console.error("Load settings error:", e);
  }
}

function updateWelcomePreview() {
  const pName = document.getElementById("settings-project-name")?.value.trim() || "Vault";
  const custom = document.getElementById("settings-welcome-text")?.value.trim();
  const previewEl = document.getElementById("settings-welcome-preview");
  if (!previewEl) return;

  if (custom) {
    let t = custom.replace(/{name}/g, "Иван").replace(/{first_name}/g, "Иван");
    t = t.replace(/{username}/g, "@ivan_crypto");
    t = t.replace(/{project_name}/g, pName);
    previewEl.innerHTML = t;
  } else {
    previewEl.innerHTML = `👋 Здравствуйте, <b>Иван</b>!<br><br>Добро пожаловать в мультивалютный криптокошелек <b>${pName}</b>.<br><br>⚡ <b>Доступные возможности:</b><br>• Хранение и операции с 10 топ-криптовалютами (BTC, ETH, USDT, TON, SOL, BNB, TRX, XRP, DOGE, USDC)<br>• Присвоение персональных адресов для пополнения<br>• Быстрый вывод и переводы средств<br>• Внутренний обмен валют<br>• Прозрачная история транзакций<br><br>Нажмите кнопку ниже, чтобы открыть кошелек 👇`;
  }
}

async function saveSettings() {
  const projectName = document.getElementById("settings-project-name").value.trim();
  const supportContact = document.getElementById("settings-support-contact").value.trim();
  const welcomeText = document.getElementById("settings-welcome-text").value.trim();

  try {
    const res = await adminApi("/api/admin/settings", {
      method: "POST",
      body: JSON.stringify({
        project_name: projectName,
        support_contact: supportContact,
        welcome_text: welcomeText
      })
    });

    alert(res.message || "Настройки успешно сохранены!");
    await loadAdminBranding();
    updateWelcomePreview();
  } catch (e) {
    alert("Ошибка при сохранении настроек: " + e.message);
  }
}

async function resetWelcomeSettings() {
  if (!confirm("Сбросить текст приветствия к стандартному шаблону?")) return;
  document.getElementById("settings-welcome-text").value = "";
  updateWelcomePreview();
  await saveSettings();
}

// ── NAV & MODALS ──
function switchSystemTab(tabName) {
  document.querySelectorAll('.subtab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.system-tab').forEach(t => {
    t.classList.remove('active');
    t.style.display = 'none';
  });

  const btn = document.getElementById('subtab-btn-' + tabName);
  if (btn) btn.classList.add('active');

  const tab = document.getElementById('systab-' + tabName);
  if (tab) {
    tab.classList.add('active');
    tab.style.display = 'block';
  }

  if (tabName === 'settings') loadSettings();
  if (tabName === 'hd') loadHdInfo();
  if (tabName === 'bcast') loadBroadcastHistory();
}

function switchPage(name) {
  const systemTabs = ['settings', 'hd', 'bcast', 'api'];
  if (systemTabs.includes(name)) {
    switchPage('system');
    switchSystemTab(name);
    return;
  }

  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

  const pg = document.getElementById('page-' + name);
  if (pg) pg.classList.add('active');
  const nb = document.getElementById('nav-' + name);
  if (nb) nb.classList.add('active');

  if (name === 'users') loadUsers();
  if (name === 'all-tx') loadAllTransactions();
  if (name === 'dash') loadDashboard();
  if (name === 'system') {
    const activeBtn = document.querySelector('.subtab-btn.active');
    const tabName = activeBtn ? activeBtn.id.replace('subtab-btn-', '') : 'settings';
    switchSystemTab(tabName);
  }
}

function openModal(name) {
  document.getElementById('modal-' + name).classList.add('show');
}
function closeModal(name) {
  document.getElementById('modal-' + name).classList.remove('show');
}
document.querySelectorAll('.modal-overlay').forEach(o => {
  o.addEventListener('click', e => { if (e.target === o) o.classList.remove('show'); });
});

document.addEventListener("DOMContentLoaded", initAdmin);
