// Vault Client WebApp Logic
let token = "";
let currentUser = null;
let currentAssets = [];
let currentTransactions = [];

const tg = window.Telegram?.WebApp;
if (tg) {
  tg.expand();
  tg.enableClosingConfirmation();
}

// ── FLOATING TOAST NOTIFICATION (БЕЗ НАЗОЙЛИВЫХ МОДАЛЬНЫХ КНОПОК "ГАРАЗД") ──
function showToast(message, isError = false) {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = `toast-pill ${isError ? 'toast-error' : 'toast-success'}`;
  const icon = isError ? '⚠️' : '✓';
  toast.innerHTML = `<span style="font-size:16px;">${icon}</span><span>${message}</span>`;
  
  toast.onclick = () => removeToast(toast);
  container.appendChild(toast);

  if (tg?.HapticFeedback) {
    if (isError) {
      tg.HapticFeedback.notificationOccurred('error');
    } else {
      tg.HapticFeedback.notificationOccurred('success');
    }
  }

  setTimeout(() => removeToast(toast), 2500);
}

function removeToast(toast) {
  if (!toast || toast.dataset.removing) return;
  toast.dataset.removing = "true";
  toast.classList.add("toast-out");
  setTimeout(() => {
    if (toast && toast.parentNode) toast.parentNode.removeChild(toast);
  }, 250);
}

// Заменяем стандартный window.alert, чтобы Telegram никогда не показал блокирующее системное окно
window.alert = function(msg) {
  showToast(String(msg || ""), false);
};

// ── CONFIG & BRANDING ──
async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    if (res.ok) {
      const cfg = await res.json();
      if (cfg.project_name) {
        document.title = `${cfg.project_name} — Crypto Wallet`;
        const logoEl = document.getElementById("topbar-logo");
        if (logoEl) {
          logoEl.textContent = cfg.project_name;
        }
        const fallbackTitle = document.getElementById("fallback-wallet-title");
        if (fallbackTitle) {
          fallbackTitle.textContent = `⚡ ${cfg.project_name} Crypto Wallet`;
        }
      }
      if (cfg.support_contact) {
        window.SUPPORT_CONTACT = cfg.support_contact;
      }
    }
  } catch (e) {
    console.warn("Could not load /api/config:", e);
  }
}

// ── INIT & AUTH ──
async function init() {
  await loadConfig();

  const initData = tg?.initData || "";
  const currentTgId = tg?.initDataUnsafe?.user?.id;
  const lastSavedTgId = localStorage.getItem("vault_auth_tg_id");

  // Если Telegram сообщил другого пользователя, немедленно очищаем старый кэш!
  if (currentTgId && lastSavedTgId && String(currentTgId) !== String(lastSavedTgId)) {
    console.log("User changed! Resetting local cache...");
    localStorage.removeItem("vault_token");
    token = "";
  }

  // Внутри Telegram WebApp: ВСЕГДА авторизуем текущего пользователя из tg.initData!
  if (initData) {
    try {
      const resp = await fetch("/api/auth/telegram", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: initData })
      });
      const data = await resp.json();
      if (data.token) {
        token = data.token;
        localStorage.setItem("vault_token", token);
        if (currentTgId) {
          localStorage.setItem("vault_auth_tg_id", String(currentTgId));
        }
      } else {
        showToast(data.detail || "Ошибка авторизации Telegram", true);
        return;
      }
    } catch (e) {
      console.error("Auth error:", e);
    }
  } else {
    // Вне Telegram: используем сохраненный токен или предлагаем открыть через бота
    token = localStorage.getItem("vault_token") || "";
    if (!token) {
      document.body.innerHTML = `
        <div style="padding: 40px 20px; text-align: center; font-family: sans-serif; color: #fff; background: #0a0a0f; min-height: 100vh;">
          <h2 style="color: #00e5a0; margin-bottom: 12px;" id="fallback-wallet-title">⚡ Crypto Wallet</h2>
          <p style="color: #888; line-height: 1.6;">
            Пожалуйста, откройте кошелек через кнопку в вашем Telegram-боте.<br>
          </p>
          <p style="color: #555; font-size: 12px; margin-top: 24px;">
            Каждый аккаунт безопасно привязывается к вашему Telegram ID.
          </p>
        </div>
      `;
      await loadConfig();
      return;
    }
  }

  await loadUserData();
  await loadBalances();
  await loadTransactions();
}

async function apiRequest(url, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { "Authorization": `Bearer ${token}` } : {}),
    ...(options.headers || {})
  };

  const resp = await fetch(url, { ...options, headers });
  if (resp.status === 401) {
    localStorage.removeItem("vault_token");
    token = "";
    showToast("Сессия устарела. Пожалуйста, обновите страницу", true);
    throw new Error("Unauthorized");
  }

  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const errorMsg = data.detail || data.message || `Ошибка сервера (${resp.status})`;
    throw new Error(errorMsg);
  }
  return data;
}

// ── LOAD USER DATA ──
async function loadUserData() {
  try {
    const data = await apiRequest("/api/user/me");
    if (data.user) {
      currentUser = data.user;
      const username = currentUser.username ? `@${currentUser.username}` : `ID: ${currentUser.telegram_id}`;
      document.getElementById("user-badge").textContent = username;
      document.getElementById("profile-username").textContent = username;
      document.getElementById("profile-id").textContent = `ID: ${currentUser.telegram_id}`;
      
      const initial = (currentUser.first_name || currentUser.username || "U")[0].toUpperCase();
      document.getElementById("user-avatar").textContent = initial;
      document.getElementById("profile-avatar").textContent = initial;

      document.getElementById("total-usd").textContent = `$${data.total_balance_usd.toFixed(2)}`;
      document.getElementById("total-btc").textContent = `${data.total_balance_btc} BTC`;
    }
  } catch (e) {
    console.error("Load user error:", e);
  }
}

// ── LOAD BALANCES (10 COINS) ──
async function loadBalances() {
  try {
    const data = await apiRequest("/api/wallet/balances");
    if (data.assets) {
      currentAssets = data.assets;
      renderAssets();
      populateCoinSelectors();
    }
  } catch (e) {
    console.error("Load balances error:", e);
  }
}

function renderAssets() {
  const homeContainer = document.getElementById("home-assets-list");
  const allContainer = document.getElementById("all-assets-list");
  
  homeContainer.innerHTML = "";
  allContainer.innerHTML = "";

  currentAssets.forEach((asset, idx) => {
    const itemHtml = `
      <div class="asset-item" onclick="openReceiveForCoin('${asset.coin}')">
        <div class="asset-icon" style="background:${asset.color}22; color:${asset.color}">
          ${asset.icon}
        </div>
        <div class="asset-info">
          <div class="asset-name">
            ${asset.name}
            ${!asset.has_address ? '<span style="font-size:9px; background:rgba(255,107,53,0.15); color:var(--warn); padding:2px 6px; border-radius:4px;">не назначен</span>' : ''}
          </div>
          <div class="asset-sub">${asset.network} · $${asset.rate_usd.toLocaleString()}</div>
        </div>
        <div class="asset-right">
          <div class="asset-balance">${asset.balance} ${asset.coin}</div>
          <div class="asset-usd">≈ $${asset.usd_value.toFixed(2)}</div>
        </div>
      </div>
    `;

    // Первые 4 на главной
    if (idx < 4) {
      homeContainer.insertAdjacentHTML("beforeend", itemHtml);
    }
    // Все 10 на странице активов
    allContainer.insertAdjacentHTML("beforeend", itemHtml);
  });
}

function populateCoinSelectors() {
  const sendSel = document.getElementById("send-coin");
  const recvSel = document.getElementById("receive-coin-select");
  const exFrom = document.getElementById("exchange-from");
  const exTo = document.getElementById("exchange-to");

  sendSel.innerHTML = "";
  recvSel.innerHTML = "";
  exFrom.innerHTML = "";
  exTo.innerHTML = "";

  currentAssets.forEach(a => {
    const opt = `<option value="${a.coin}">${a.name} (${a.coin}) — Баланс: ${a.balance}</option>`;
    sendSel.insertAdjacentHTML("beforeend", opt);
    recvSel.insertAdjacentHTML("beforeend", `<option value="${a.coin}">${a.name} (${a.coin}) [${a.network}]</option>`);
    exFrom.insertAdjacentHTML("beforeend", `<option value="${a.coin}">${a.coin} ($${a.rate_usd})</option>`);
    exTo.insertAdjacentHTML("beforeend", `<option value="${a.coin}">${a.coin} ($${a.rate_usd})</option>`);
  });

  if (exTo.options.length > 1) {
    exTo.selectedIndex = 1;
  }
}

// ── LOAD TRANSACTIONS ──
async function loadTransactions() {
  try {
    const data = await apiRequest("/api/transactions");
    if (data.transactions) {
      currentTransactions = data.transactions;
      renderTransactions();
    }
  } catch (e) {
    console.error("Load tx error:", e);
  }
}

function renderTransactions() {
  const homeContainer = document.getElementById("home-tx-list");
  const fullContainer = document.getElementById("full-tx-list");
  
  homeContainer.innerHTML = "";
  fullContainer.innerHTML = "";

  if (currentTransactions.length === 0) {
    const empty = `<div style="text-align:center; padding:24px; color:var(--muted); font-size:13px;">Транзакций пока нет</div>`;
    homeContainer.innerHTML = empty;
    fullContainer.innerHTML = empty;
    return;
  }

  currentTransactions.forEach((tx, idx) => {
    const isPending = tx.status === "pending";
    const isRejected = tx.status === "rejected";
    const isOut = tx.type === "withdraw" || tx.type === "p2p_out" || tx.type === "manual_out" || tx.type === "binary_bet" || tx.type === "spot_sell";

    let icon = "⬇️";
    let iconClass = "in";
    let sign = "+";
    let amountClass = "in";

    if (tx.type === "binary_bet") {
      icon = "⚡";
      iconClass = "out";
      sign = "-";
      amountClass = "out";
    } else if (tx.type === "binary_win") {
      icon = "🏆";
      iconClass = "in";
      sign = "+";
      amountClass = "in";
    } else if (tx.type === "binary_refund") {
      icon = "🤝";
      iconClass = "pend";
      sign = "";
      amountClass = "pend";
    } else if (tx.type === "futures_open") {
      icon = "⚡";
      iconClass = "out";
      sign = "-";
      amountClass = "out";
    } else if (tx.type === "futures_close") {
      icon = "🎯";
      iconClass = "in";
      sign = "+";
      amountClass = "in";
    } else if (tx.type === "spot_buy") {
      icon = "🛒";
      iconClass = "in";
      sign = "+";
      amountClass = "in";
    } else if (tx.type === "spot_sell") {
      icon = "🏷️";
      iconClass = "out";
      sign = "-";
      amountClass = "out";
    } else if (isPending) {
      icon = "⏳";
      iconClass = "pend";
      sign = "";
      amountClass = "pend";
    } else if (isRejected) {
      icon = "❌";
      iconClass = "out";
      sign = "";
      amountClass = "out";
    } else if (isOut) {
      icon = "⬆️";
      iconClass = "out";
      sign = "-";
      amountClass = "out";
    }

    const dateStr = new Date(tx.created_at).toLocaleString("ru-RU", {
      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"
    });

    const statusText = isPending ? "ожидает подтверждения" : (isRejected ? "отклонено" : "завершено");
    const statusClass = isPending ? "pending" : "";

    const itemHtml = `
      <div class="tx-item">
        <div class="tx-icon ${iconClass}">${icon}</div>
        <div class="tx-info">
          <div class="tx-name">${tx.comment || tx.type}</div>
          <div class="tx-date">${dateStr} · #${tx.id}</div>
        </div>
        <div>
          <div class="tx-amount ${amountClass}">${sign}${tx.amount} ${tx.coin}</div>
          <div class="tx-status ${statusClass}">${statusText}</div>
        </div>
      </div>
    `;

    if (idx < 5) homeContainer.insertAdjacentHTML("beforeend", itemHtml);
    fullContainer.insertAdjacentHTML("beforeend", itemHtml);
  });
}

// ── NAVIGATION ──
function switchPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  const pg = document.getElementById('page-' + name);
  if (pg) pg.classList.add('active');
  const nb = document.getElementById('nav-' + name);
  if (nb) nb.classList.add('active');

  if (name === 'trading') {
    onOpenTradingPage();
  }
}

// ── MODALS ──
function openModal(name) {
  document.getElementById('modal-' + name).classList.add('show');
}
function closeModal(name) {
  document.getElementById('modal-' + name).classList.remove('show');
}
document.querySelectorAll('.modal-overlay').forEach(o => {
  o.addEventListener('click', e => { if (e.target === o) o.classList.remove('show'); });
});

// ── SEND MODAL ──
function openSendModal(mode) {
  updateSendBalanceHint();
  if (mode === 'p2p') {
    document.getElementById('send-to').placeholder = "@username или Telegram ID";
    document.getElementById('send-modal-title').textContent = "P2P Перевод по @username";
  } else {
    document.getElementById('send-to').placeholder = "Адрес блокчейн кошелька";
    document.getElementById('send-modal-title').textContent = "Отправить криптовалюту";
  }
  openModal('send');
}

function updateSendBalanceHint() {
  const coin = document.getElementById('send-coin').value;
  const asset = currentAssets.find(a => a.coin === coin);
  if (asset) {
    document.getElementById('send-balance-hint').textContent = `Доступно: ${asset.balance} ${asset.coin}`;
    document.getElementById('send-memo-group').style.display = asset.has_memo ? 'block' : 'none';
  }
}

async function submitSend() {
  const coin = document.getElementById('send-coin').value;
  const to = document.getElementById('send-to').value.trim();
  const amount = parseFloat(document.getElementById('send-amount').value);
  const memo = document.getElementById('send-memo')?.value?.trim();

  if (!to || isNaN(amount) || amount <= 0) {
    showToast("Пожалуйста, заполните все поля корректно", true);
    return;
  }

  try {
    let res;
    if (to.startsWith("@") || (!to.startsWith("0x") && !to.startsWith("bc1") && !to.startsWith("T") && to.length < 20)) {
      // P2P перевод
      res = await apiRequest("/api/transfer/p2p", {
        method: "POST",
        body: JSON.stringify({ recipient: to, coin, amount })
      });
    } else {
      // Обычный вывод
      res = await apiRequest("/api/transfer/request", {
        method: "POST",
        body: JSON.stringify({ coin, amount, to_address: to, memo })
      });
    }

    closeModal('send');
    showToast(res.message || "Заявка успешно отправлена!");
    await loadBalances();
    await loadTransactions();
    await loadUserData();
  } catch (e) {
    showToast("Ошибка: " + e.message, true);
  }
}

// ── RECEIVE MODAL ──
function openReceiveModal() {
  openModal('receive');
  loadReceiveDetails();
}

function openReceiveForCoin(coin) {
  const sel = document.getElementById('receive-coin-select');
  sel.value = coin;
  openReceiveModal();
}

function openReceiveForDefault() {
  openReceiveForCoin('USDT');
}

async function loadReceiveDetails() {
  const coin = document.getElementById('receive-coin-select').value;
  const content = document.getElementById('receive-content');
  content.innerHTML = `<div style="text-align:center; padding:20px; color:var(--muted);">Загрузка...</div>`;

  try {
    const data = await apiRequest(`/api/wallet/address?coin=${coin}`);
    const isFiat = data.is_fiat || coin === 'USD' || coin === 'RUB';

    if (data.has_address) {
      if (isFiat) {
        // Банковский режимный IBAN
        content.innerHTML = `
          <div style="background:var(--surface2); border:1px solid rgba(0,229,160,0.3); border-radius:16px; padding:16px; margin:12px 0;">
            <div style="display:flex; align-items:center; gap:10px; margin-bottom:14px;">
              <div style="font-size:28px;">🏦</div>
              <div>
                <div style="font-weight:700; font-size:15px;">Режимный счет / IBAN (${coin})</div>
                <div style="font-size:11px; color:var(--muted); font-family:'Space Mono', monospace;">Банковские реквизиты</div>
              </div>
            </div>
            
            <div style="margin-bottom:12px;">
              <div style="font-size:11px; color:var(--muted); text-transform:uppercase; margin-bottom:4px;">IBAN / Номер счёта:</div>
              <div class="wallet-addr" onclick="copyText('${data.address}')">
                <span style="font-family:'Space Mono', monospace; font-size:13px; color:var(--accent); font-weight:700; word-break:break-all;">${data.address}</span>
                <span class="copy-btn">копировать</span>
              </div>
            </div>

            ${data.memo ? `
            <div style="margin-bottom:12px;">
              <div style="font-size:11px; color:var(--muted); text-transform:uppercase; margin-bottom:4px;">Банк / Получатель / Назначение:</div>
              <div class="wallet-addr" onclick="copyText('${data.memo}')">
                <span style="font-family:'Space Mono', monospace; font-size:12px; word-break:break-all;">${data.memo}</span>
                <span class="copy-btn">копировать</span>
              </div>
            </div>
            ` : ''}

            <div class="note" style="margin-top:12px;">
              <b>Инструкция:</b> Осуществите межбанковский перевод по указанным реквизитам. Зачисление на баланс кошелька происходит в течение нескольких минут после подтверждения оператором.
            </div>
          </div>
        `;
      } else {
        // Обычный крипто-кошелек с QR
        const memoHtml = data.memo ? `
          <div style="margin-top:10px">
            <div style="font-size:11px; color:var(--muted); text-transform:uppercase;">Destination Tag / Memo:</div>
            <div class="wallet-addr" onclick="copyText('${data.memo}')" style="margin-top:4px">
              <span>${data.memo}</span>
              <span class="copy-btn">копировать</span>
            </div>
          </div>
        ` : '';

        content.innerHTML = `
          <div style="text-align:center; margin-bottom:12px">
            <div style="font-size:12px; color:var(--muted); margin-bottom:8px">Сеть: <b>${data.network}</b></div>
            <div class="qr-box">
              <img src="${data.qr_code}" alt="QR-код">
            </div>
            <div class="wallet-addr" onclick="copyText('${data.address}')">
              <span style="word-break:break-all; font-size:11px">${data.address}</span>
              <span class="copy-btn">копировать</span>
            </div>
            ${memoHtml}
          </div>
          <div class="note">Отправляйте исключительно <b>${coin} (${data.network})</b> на данный адрес. Зачисление произойдет после подтверждения оператором.</div>
        `;
      }
    } else {
      if (isFiat) {
        content.innerHTML = `
          <div class="no-addr-box">
            <div class="no-addr-title">Режимный счет (IBAN) для ${coin} еще не присвоен</div>
            <div class="no-addr-sub">Отправьте запрос администратору на выделение персонального счета (IBAN / банковских реквизитов) для пополнения и вывода средств.</div>
            <button class="btn-primary" onclick="requestAddress('${coin}')">⚡ Запросить реквизиты (IBAN)</button>
          </div>
        `;
      } else {
        content.innerHTML = `
          <div class="no-addr-box">
            <div class="no-addr-title">Кошелек ${coin} еще не присвоен</div>
            <div class="no-addr-sub">Для получения адреса отправьте запрос администратору. Администратор выделит вам персональный адрес и бот пришлет уведомление.</div>
            <button class="btn-primary" onclick="requestAddress('${coin}')">⚡ Запросить адрес ${coin}</button>
          </div>
        `;
      }
    }
  } catch (e) {
    content.innerHTML = `<div style="color:var(--red); padding:16px; text-align:center;">Ошибка загрузки адреса</div>`;
  }
}

async function requestAddress(coin) {
  try {
    const res = await apiRequest("/api/wallet/request_address", {
      method: "POST",
      body: JSON.stringify({ coin })
    });
    showToast(res.message || "Запрос отправлен администратору!");
    closeModal('receive');
  } catch (e) {
    showToast("Ошибка: " + e.message, true);
  }
}

function copyText(str) {
  navigator.clipboard?.writeText(str);
  if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
  showToast("✓ Скопировано в буфер обмена");
}

// ── EXCHANGE MODAL ──
function openExchangeModal() {
  calcExchangePreview();
  openModal('exchange');
}

function calcExchangePreview() {
  const from = document.getElementById('exchange-from').value;
  const to = document.getElementById('exchange-to').value;
  const amt = parseFloat(document.getElementById('exchange-amount').value) || 0;

  const aFrom = currentAssets.find(a => a.coin === from);
  const aTo = currentAssets.find(a => a.coin === to);

  if (aFrom && aTo && amt > 0) {
    const usdVal = amt * aFrom.rate_usd;
    const est = usdVal / aTo.rate_usd;
    document.getElementById('exchange-estimate').textContent = `≈ ${est.toFixed(4)} ${to} (по курсу $${aTo.rate_usd})`;
  } else {
    document.getElementById('exchange-estimate').textContent = `≈ 0.00`;
  }
}

async function submitExchange() {
  const from = document.getElementById('exchange-from').value;
  const to = document.getElementById('exchange-to').value;
  const amt = parseFloat(document.getElementById('exchange-amount').value);

  if (!amt || amt <= 0) {
    showToast("Введите корректную сумму", true);
    return;
  }

  try {
    const res = await apiRequest("/api/exchange/request", {
      method: "POST",
      body: JSON.stringify({ from_coin: from, to_coin: to, amount: amt })
    });
    closeModal('exchange');
    showToast(res.message || "Заявка на обмен создана!");
    await loadBalances();
    await loadTransactions();
    await loadUserData();
  } catch (e) {
    showToast("Ошибка: " + e.message, true);
  }
}

// ══════════════════════════════════════════════════════════
// ── TRADING ENGINE (БИНАРНЫЕ ОПЦИОНЫ & СПОТ РЫНОК) ──
// ══════════════════════════════════════════════════════════
let selectedTradingPair = "BTC/USDT";
let currentTradingMode = "binary"; // 'binary' или 'futures'
let currentLivePrice = 0;
let lastLivePrice = 0;
let chartPoints = [];
let chartCandles = [];
let currentChartType = (function() {
  try { return localStorage.getItem("vault_chart_type") || "candles"; } catch(e) { return "candles"; }
})();
let chartTimeframe = "1m";
let activeBinaryBets = [];
let activeFuturesPositions = [];
let futuresSide = "LONG";
let futuresLeverage = 10;
let tradeTickerInterval = null;
let betsCountdownInterval = null;

function onOpenTradingPage() {
  updateTradingBalanceHints();

  // Синхронизируем состояние кнопок типа графика и таймфрейма
  document.getElementById("chart-type-line")?.classList.toggle("active", currentChartType === "line");
  document.getElementById("chart-type-candles")?.classList.toggle("active", currentChartType === "candles");
  document.querySelectorAll(".tf-scroll-bar .tf-btn").forEach(b => b.classList.remove("active"));
  document.getElementById(`tf-${chartTimeframe}`)?.classList.add("active");
  const tfLbl = document.getElementById("chart-timeframe-label");
  if (tfLbl) tfLbl.textContent = chartTimeframe;

  onTradingPairChanged();
  loadActiveBinaryBets();
  loadBinaryHistory();
  loadActiveFuturesPositions();
  loadFuturesHistory();

  if (!tradeTickerInterval) {
    tradeTickerInterval = setInterval(updateLivePriceTicker, 1500);
  }
  if (!betsCountdownInterval) {
    betsCountdownInterval = setInterval(updateBetsCountdowns, 1000);
  }
}

function updateTradingBalanceHints() {
  const usdtAsset = currentAssets.find(a => a.coin === "USDT");
  const usdtBal = usdtAsset ? usdtAsset.balance : 0;
  const usdtEl = document.getElementById("binary-usdt-balance");
  if (usdtEl) usdtEl.textContent = `Баланс: $${usdtBal.toFixed(2)}`;
  updatePayoutCalc();
  updateFuturesUi();
}

function setTradingMode(mode) {
  if (mode === "spot") mode = "futures";
  currentTradingMode = mode;
  document.getElementById("tab-trade-binary")?.classList.toggle("active", mode === "binary");
  document.getElementById("tab-trade-futures")?.classList.toggle("active", mode === "futures");
  document.getElementById("tab-trade-spot")?.classList.toggle("active", false);
  
  const pBin = document.getElementById("panel-binary");
  const pFut = document.getElementById("panel-futures");
  if (pBin) pBin.style.display = mode === "binary" ? "block" : "none";
  if (pFut) pFut.style.display = mode === "futures" ? "block" : "none";

  if (mode === "futures") {
    updateFuturesUi();
    loadActiveFuturesPositions();
    loadFuturesHistory();
  }
}

async function onTradingPairChanged() {
  const sel = document.getElementById("trade-pair-select");
  if (sel) selectedTradingPair = sel.value;

  chartPoints = [];
  chartCandles = [];
  await updateLivePriceTicker();
  await loadChartData();

  if (currentTradingMode === "futures") {
    updateFuturesUi();
    loadActiveFuturesPositions();
  }
}

function setChartType(type) {
  if (type !== "line" && type !== "candles") type = "candles";
  currentChartType = type;
  try {
    localStorage.setItem("vault_chart_type", type);
  } catch (e) {}

  document.getElementById("chart-type-line")?.classList.toggle("active", type === "line");
  document.getElementById("chart-type-candles")?.classList.toggle("active", type === "candles");

  drawChart();
}

function setTimeframe(tf) {
  chartTimeframe = tf;
  document.querySelectorAll(".tf-scroll-bar .tf-btn").forEach(b => b.classList.remove("active"));
  const btn = document.getElementById(`tf-${tf}`);
  if (btn) {
    btn.classList.add("active");
    btn.scrollIntoView({ behavior: "smooth", inline: "nearest", block: "nearest" });
  }

  const lbl = document.getElementById("chart-timeframe-label");
  if (lbl) lbl.textContent = tf;

  loadChartData();
}

async function loadChartData() {
  try {
    const data = await apiRequest(`/api/trading/chart?pair=${encodeURIComponent(selectedTradingPair)}&timeframe=${encodeURIComponent(chartTimeframe)}&limit=42`);
    if (data.candles && data.candles.length > 0) {
      chartCandles = data.candles;
      chartPoints = data.candles.map(c => c.close);
      if (currentLivePrice > 0) {
        const last = chartCandles[chartCandles.length - 1];
        last.close = currentLivePrice;
        if (currentLivePrice > last.high) last.high = currentLivePrice;
        if (currentLivePrice < last.low) last.low = currentLivePrice;
        chartPoints[chartPoints.length - 1] = currentLivePrice;
      }
      drawChart();
    }
  } catch (e) {
    console.error("Load chart error:", e);
  }
}

async function updateLivePriceTicker() {
  try {
    const data = await apiRequest(`/api/trading/price?pair=${encodeURIComponent(selectedTradingPair)}`);
    if (data.price) {
      lastLivePrice = currentLivePrice || data.price;
      currentLivePrice = data.price;

      const priceEl = document.getElementById("live-price-val");
      const chgEl = document.getElementById("live-price-chg");
      const timeEl = document.getElementById("ticker-time");

      const decimals = selectedTradingPair.includes("RUB") ? 2 : (currentLivePrice < 1 ? 4 : (currentLivePrice < 10 ? 3 : 2));
      const symbolPrefix = selectedTradingPair.endsWith("RUB") ? "₽" : "$";

      priceEl.textContent = `${symbolPrefix}${currentLivePrice.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;

      // Анимация изменения цены
      if (currentLivePrice > lastLivePrice) {
        priceEl.style.color = "var(--green)";
        setTimeout(() => { if (priceEl) priceEl.style.color = "var(--text)"; }, 400);
      } else if (currentLivePrice < lastLivePrice) {
        priceEl.style.color = "var(--red)";
        setTimeout(() => { if (priceEl) priceEl.style.color = "var(--text)"; }, 400);
      }

      if (data.change_24h !== undefined) {
        const sign = data.change_24h >= 0 ? "+" : "";
        chgEl.textContent = `${sign}${data.change_24h.toFixed(2)}%`;
        chgEl.className = `ticker-change ${data.change_24h >= 0 ? "up" : "down"}`;
      }

      if (timeEl) {
        const now = new Date();
        timeEl.textContent = now.toTimeString().split(" ")[0];
      }

      // Добавляем точку и свечу на график
      if (chartCandles.length === 0) {
        chartCandles.push({
          time: Math.floor(Date.now() / 1000),
          open: currentLivePrice,
          high: currentLivePrice,
          low: currentLivePrice,
          close: currentLivePrice,
          volume: 1
        });
        chartPoints.push(currentLivePrice);
      } else {
        const lastCandle = chartCandles[chartCandles.length - 1];
        lastCandle.close = currentLivePrice;
        if (currentLivePrice > lastCandle.high) lastCandle.high = currentLivePrice;
        if (currentLivePrice < lastCandle.low) lastCandle.low = currentLivePrice;
        chartPoints[chartPoints.length - 1] = currentLivePrice;

        // Для таймфрейма 1m симулируем рождение новой свечи периодически
        if (chartTimeframe === "1m" && Math.random() > 0.88 && chartCandles.length < 45) {
          chartCandles.push({
            time: Math.floor(Date.now() / 1000),
            open: currentLivePrice,
            high: currentLivePrice,
            low: currentLivePrice,
            close: currentLivePrice,
            volume: 1
          });
          chartPoints.push(currentLivePrice);
          if (chartCandles.length > 45) {
            chartCandles.shift();
            chartPoints.shift();
          }
        }
      }

      drawChart();

      if (currentTradingMode === "futures" || currentTradingMode === "spot") {
        recalcLiveFuturesPnL();
        calcFuturesSummary();
      }
    }
  } catch (e) {
    console.error("Ticker error:", e);
  }
}

function drawCanvasPill(ctx, x, y, w, h, radius, fillColor, strokeColor) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + w - radius, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
  ctx.lineTo(x + w, y + h - radius);
  ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
  ctx.lineTo(x + radius, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
  if (fillColor) {
    ctx.fillStyle = fillColor;
    ctx.fill();
  }
  if (strokeColor) {
    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = 1;
    ctx.stroke();
  }
}

// ── РИСОВАНИЕ ГРАФИКА (ЛИНИЯ / ЯПОНСКИЕ СВЕЧИ) НА HTML5 CANVAS ──
function drawChart() {
  const canvas = document.getElementById("trade-canvas");
  const count = chartCandles.length > 0 ? chartCandles.length : chartPoints.length;
  if (!canvas || count < 2) return;

  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return;

  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = rect.height;
  const padTop = 15;
  const padBottom = 20;
  const padRight = 55;

  ctx.clearRect(0, 0, W, H);

  // Определение минимума и максимума цен
  let minP, maxP;
  if (currentChartType === "candles" && chartCandles.length > 0) {
    minP = Math.min(...chartCandles.map(c => c.low));
    maxP = Math.max(...chartCandles.map(c => c.high));
  } else {
    minP = Math.min(...chartPoints);
    maxP = Math.max(...chartPoints);
  }

  if (minP === maxP) {
    minP *= 0.998;
    maxP *= 1.002;
  }
  const diff = maxP - minP;
  minP -= diff * 0.08;
  maxP += diff * 0.08;

  const chartW = W - padRight;
  const chartH = H - padTop - padBottom;

  const getY = p => padTop + (1 - (p - minP) / (maxP - minP)) * chartH;
  const getX = i => (i / Math.max(1, chartPoints.length - 1)) * chartW;

  // 1. Координатная сетка цен
  ctx.strokeStyle = "rgba(255, 255, 255, 0.05)";
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  for (let i = 1; i <= 3; i++) {
    const y = padTop + (chartH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(chartW, y);
    ctx.stroke();

    const priceAtY = maxP - ((maxP - minP) / 4) * i;
    ctx.fillStyle = "var(--muted)";
    ctx.font = "9px 'Space Mono', monospace";
    ctx.textAlign = "left";
    const dec = priceAtY < 1 ? 4 : (priceAtY < 10 ? 3 : (priceAtY > 999 ? 0 : 2));
    ctx.fillText(priceAtY.toFixed(dec), chartW + 6, y + 3);
  }
  ctx.setLineDash([]);

  // 2. Отрисовка выбранного типа графика
  if (currentChartType === "candles" && chartCandles.length > 0) {
    // ── РЕЖИМ: ЯПОНСКИЕ СВЕЧИ ──
    const n = chartCandles.length;
    const candleSlot = chartW / n;
    const candleW = Math.max(3, Math.min(10, candleSlot * 0.72));

    for (let i = 0; i < n; i++) {
      const c = chartCandles[i];
      const isUp = c.close >= c.open;
      const color = isUp ? "#00e5a0" : "#ff4d6a";
      const xCenter = i * candleSlot + candleSlot / 2;

      const highY = getY(c.high);
      const lowY = getY(c.low);
      const openY = getY(c.open);
      const closeY = getY(c.close);

      // Фитиль (Wick)
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(xCenter, highY);
      ctx.lineTo(xCenter, lowY);
      ctx.stroke();

      // Тело свечи (Body)
      const bodyTop = Math.min(openY, closeY);
      const bodyH = Math.max(2, Math.abs(closeY - openY));
      ctx.fillStyle = color;
      ctx.fillRect(xCenter - candleW / 2, bodyTop, candleW, bodyH);
    }
  } else {
    // ── РЕЖИМ: НЕОНОВАЯ ЛИНИЯ ──
    const grad = ctx.createLinearGradient(0, padTop, 0, H - padBottom);
    grad.addColorStop(0, "rgba(0, 229, 160, 0.25)");
    grad.addColorStop(1, "rgba(0, 229, 160, 0.0)");

    ctx.beginPath();
    ctx.moveTo(getX(0), getY(chartPoints[0]));
    for (let i = 1; i < chartPoints.length; i++) {
      ctx.lineTo(getX(i), getY(chartPoints[i]));
    }
    ctx.lineTo(chartW, H - padBottom);
    ctx.lineTo(0, H - padBottom);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Линия котировки
    ctx.beginPath();
    ctx.moveTo(getX(0), getY(chartPoints[0]));
    for (let i = 1; i < chartPoints.length; i++) {
      ctx.lineTo(getX(i), getY(chartPoints[i]));
    }
    ctx.strokeStyle = "#00e5a0";
    ctx.lineWidth = 2.2;
    ctx.shadowColor = "#00e5a0";
    ctx.shadowBlur = 8;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Точка текущей цены
    const lastX = chartW;
    const lastY = getY(chartPoints[chartPoints.length - 1]);
    ctx.beginPath();
    ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#00e5a0";
    ctx.fill();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  // 3. Пунктирная линия текущей цены
  const currentP = currentLivePrice || (chartCandles.length > 0 ? chartCandles[chartCandles.length - 1].close : chartPoints[chartPoints.length - 1]);
  const currentY = getY(currentP);

  ctx.setLineDash([3, 3]);
  ctx.strokeStyle = "rgba(0, 229, 160, 0.4)";
  ctx.beginPath();
  ctx.moveTo(0, currentY);
  ctx.lineTo(chartW, currentY);
  ctx.stroke();
  ctx.setLineDash([]);

  // Бейдж текущей цены на шкале
  ctx.fillStyle = "#00e5a0";
  ctx.fillRect(chartW + 4, currentY - 8, 48, 16);
  ctx.fillStyle = "#000000";
  ctx.font = "bold 9px 'Space Mono', monospace";
  ctx.textAlign = "center";
  const pDec = currentP < 1 ? 4 : (currentP < 10 ? 3 : (currentP > 999 ? 0 : 2));
  ctx.fillText(currentP.toFixed(pDec), chartW + 28, currentY + 3);

  // 6. Сбор всех активных отметок на графике (бинарные и фьючерсы)
  const chartMarks = [];

  activeBinaryBets.filter(b => b.pair === selectedTradingPair).forEach(bet => {
    const sY = getY(bet.strike_price);
    if (sY >= padTop && sY <= H - padBottom) {
      const isCall = bet.direction === "call";
      chartMarks.push({
        y: sY,
        color: isCall ? "#00e5a0" : "#ff4d6a",
        text: `★ ${bet.direction.toUpperCase()} $${bet.strike_price > 999 ? bet.strike_price.toFixed(0) : bet.strike_price.toFixed(1)}`
      });
    }
  });

  activeFuturesPositions.filter(p => p.pair === selectedTradingPair).forEach(pos => {
    const sY = getY(pos.entry_price);
    if (sY >= padTop && sY <= H - padBottom) {
      const isLong = pos.side === "LONG";
      chartMarks.push({
        y: sY,
        color: isLong ? "#00e5a0" : "#ff4d6a",
        text: `${isLong ? '▲ LONG' : '▼ SHORT'} ${pos.leverage}x $${pos.entry_price > 999 ? pos.entry_price.toFixed(0) : pos.entry_price.toFixed(1)}`
      });
    }
  });

  // 1) Отрисовка пунктирных горизонтальных линий уровней
  chartMarks.forEach(m => {
    ctx.setLineDash([2, 2]);
    ctx.strokeStyle = m.color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, m.y);
    ctx.lineTo(chartW, m.y);
    ctx.stroke();
    ctx.setLineDash([]);
  });

  // 2) Отрисовка бейджей с защитой от наложения (Anti-Collision & Staggering)
  const placedBadges = [];
  ctx.font = "bold 8.5px 'Space Mono', monospace";

  chartMarks.forEach(m => {
    const tw = ctx.measureText(m.text).width;
    const badgeW = tw + 10;
    const badgeH = 15;
    let badgeX = 6;
    let badgeY = Math.max(padTop, Math.min(H - padBottom - badgeH, m.y - 7));

    // Алгоритм предотвращения наложений
    let overlapping = true;
    let attempts = 0;
    while (overlapping && attempts < 12) {
      attempts++;
      overlapping = false;
      for (const pb of placedBadges) {
        const xOverlap = !(badgeX + badgeW + 4 < pb.x || badgeX > pb.x + pb.w + 4);
        const yOverlap = !(badgeY + badgeH + 2 < pb.y || badgeY > pb.y + pb.h + 2);

        if (xOverlap && yOverlap) {
          overlapping = true;
          // Сдвигаем вправо вдоль той же горизонтальной линии
          if (pb.x + pb.w + 6 + badgeW < chartW - 5) {
            badgeX = pb.x + pb.w + 6;
          } else {
            // Если места справа нет, сдвигаем на следующую строку вниз
            badgeX = 6;
            badgeY = pb.y + pb.h + 3;
          }
          break;
        }
      }
    }

    placedBadges.push({ x: badgeX, y: badgeY, w: badgeW, h: badgeH });

    // Рисуем аккуратную плашку с темным фоном и неоновой рамкой
    drawCanvasPill(ctx, badgeX, badgeY, badgeW, badgeH, 4, "rgba(15, 17, 26, 0.92)", m.color);

    // Рисуем текст метки
    ctx.fillStyle = m.color;
    ctx.textAlign = "left";
    ctx.fillText(m.text, badgeX + 5, badgeY + 11);
  });
}

// ── БИНАРНЫЕ ОПЦИОНЫ: ЭКСПИРАЦИЯ, СТАВКИ ──
function selectExpiration(seconds, el) {
  selectedExpiration = seconds;
  document.querySelectorAll(".exp-btn").forEach(b => b.classList.remove("active"));
  if (el) el.classList.add("active");
  updatePayoutCalc();
}

function setQuickStake(val) {
  const inp = document.getElementById("binary-stake-input");
  if (!inp) return;
  if (val === "MAX") {
    const usdtAsset = currentAssets.find(a => a.coin === "USDT");
    inp.value = usdtAsset ? Math.floor(usdtAsset.balance) : 0;
  } else {
    inp.value = val;
  }
  updatePayoutCalc();
}

function updatePayoutCalc() {
  const stake = parseFloat(document.getElementById("binary-stake-input")?.value) || 0;
  const payout = stake * 1.85; // +85% доходность
  const payoutEl = document.getElementById("binary-payout-val");
  if (payoutEl) {
    payoutEl.textContent = `$${payout.toFixed(2)}`;
  }
}

async function placeBinaryBet(direction) {
  const stake = parseFloat(document.getElementById("binary-stake-input")?.value);
  if (isNaN(stake) || stake <= 0) {
    showToast("Пожалуйста, введите сумму сделки", true);
    return;
  }

  const usdtAsset = currentAssets.find(a => a.coin === "USDT");
  const usdtBal = usdtAsset ? usdtAsset.balance : 0;
  if (stake > usdtBal) {
    showToast(`Недостаточно средств. Ваш баланс USDT: $${usdtBal.toFixed(2)}`, true);
    return;
  }

  try {
    const res = await apiRequest("/api/trading/binary/bet", {
      method: "POST",
      body: JSON.stringify({
        pair: selectedTradingPair,
        direction: direction,
        stake: stake,
        stake_amount: stake,
        stake_coin: "USDT",
        duration: selectedExpiration,
        duration_seconds: selectedExpiration
      })
    });

    if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    showToast(res.message || "✓ Сделка успешно открыта!");

    await loadBalances();
    updateTradingBalanceHints();
    await loadActiveBinaryBets();
    await loadBinaryHistory();
    await loadTransactions();
  } catch (e) {
    if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('error');
    showToast("Ошибка открытия сделки: " + e.message, true);
  }
}

async function loadActiveBinaryBets() {
  try {
    const data = await apiRequest("/api/trading/binary/active");
    const bets = data.bets || data.active_bets || [];
    activeBinaryBets = bets;
    renderActiveBinaryBets();
  } catch (e) {
    console.error("Active bets error:", e);
  }
}

function renderActiveBinaryBets() {
  const countEl = document.getElementById("active-bets-count");
  const listEl = document.getElementById("active-bets-list");
  if (countEl) countEl.textContent = activeBinaryBets.length;
  if (!listEl) return;

  if (activeBinaryBets.length === 0) {
    listEl.innerHTML = `<div style="text-align:center; padding:12px; color:var(--muted); font-size:12px;">Нет активных сделок</div>`;
    return;
  }

  listEl.innerHTML = "";
  activeBinaryBets.forEach(bet => {
    const isCall = (bet.direction || "").toLowerCase() === "call";
    const dirClass = isCall ? "call" : "put";
    const dirIcon = isCall ? "↗ ВВЕРХ" : "↘ ВНИЗ";

    const strikePrice = Number(bet.strike_price || bet.entry_price || 0);
    const stake = Number(bet.stake || bet.stake_amount || 0);
    const potentialPayout = Number(bet.potential_payout || (stake * 1.85));
    const remainingSec = (bet.remaining_seconds !== undefined) ? bet.remaining_seconds : (bet.seconds_remaining !== undefined ? bet.seconds_remaining : 30);

    const inProfit = isCall ? (currentLivePrice >= strikePrice) : (currentLivePrice <= strikePrice);
    const profitColor = inProfit ? "var(--green)" : "var(--red)";
    const profitText = inProfit ? `+$${potentialPayout.toFixed(2)} (+85%)` : `-$${stake.toFixed(2)}`;

    const card = `
      <div class="active-bet-card">
        <div class="abc-top">
          <span class="abc-dir ${dirClass}">${bet.pair} · ${dirIcon}</span>
          <span class="abc-timer" id="bet-timer-${bet.id}">${remainingSec}с</span>
        </div>
        <div class="abc-details">
          <span>Страйк: <b>$${strikePrice.toFixed(2)}</b></span>
          <span>Ставка: <b>$${stake.toFixed(2)}</b></span>
          <span style="color:${profitColor}; font-weight:700;">${profitText}</span>
        </div>
        <div class="abc-prog-track">
          <div class="abc-prog-bar" id="bet-bar-${bet.id}" style="width: 100%;"></div>
        </div>
      </div>
    `;
    listEl.insertAdjacentHTML("beforeend", card);
  });
}

function updateBetsCountdowns() {
  if (activeBinaryBets.length === 0) return;

  let hasExpired = false;
  activeBinaryBets.forEach(bet => {
    let rem = (bet.remaining_seconds !== undefined) ? bet.remaining_seconds : bet.seconds_remaining;
    if (rem > 0) {
      rem--;
      bet.remaining_seconds = rem;
      bet.seconds_remaining = rem;
      const timerEl = document.getElementById(`bet-timer-${bet.id}`);
      if (timerEl) {
        timerEl.textContent = `${rem}с`;
      }
      const barEl = document.getElementById(`bet-bar-${bet.id}`);
      if (barEl) {
        const totalDuration = bet.duration || bet.duration_seconds || 30;
        const pct = Math.max(0, (rem / totalDuration) * 100);
        barEl.style.width = `${pct}%`;
      }
    } else {
      hasExpired = true;
    }
  });

  if (hasExpired) {
    // Ждем 1.2 секунды пока бэкенд воркер рассчитает результат, затем обновляем
    setTimeout(async () => {
      await loadActiveBinaryBets();
      await loadBinaryHistory();
      await loadBalances();
      await loadTransactions();
      updateTradingBalanceHints();
    }, 1200);
  }
}

async function loadBinaryHistory() {
  try {
    const data = await apiRequest("/api/trading/binary/history?limit=15");
    const container = document.getElementById("history-bets-list");
    if (!container) return;

    const list = data.history || data.bets || [];
    if (list.length === 0) {
      container.innerHTML = `<div style="text-align:center; padding:10px; color:var(--muted); font-size:11px;">История пока пуста</div>`;
      return;
    }

    container.innerHTML = "";
    list.forEach(h => {
      const isWin = h.status === "won";
      const isLoss = h.status === "lost";
      const badgeClass = isWin ? "in" : (isLoss ? "out" : "pend");
      
      const stake = Number(h.stake || h.stake_amount || 0);
      const profit = Number(h.profit !== undefined ? h.profit : (isWin ? ((h.payout_amount || 0) - stake) : 0));
      const strikePrice = Number(h.strike_price || h.entry_price || 0);
      const exitPrice = (h.exit_price !== null && h.exit_price !== undefined) ? Number(h.exit_price) : null;

      let badgeText = "АКТИВЕН";
      let icon = "⏳";
      if (isWin) {
        badgeText = `WIN +$${profit.toFixed(2)}`;
        icon = "🏆";
      } else if (isLoss) {
        badgeText = `LOSS -$${stake.toFixed(2)}`;
        icon = "📉";
      } else if (h.status === "tie") {
        badgeText = "REFUND $0";
        icon = "🤝";
      }

      const dirName = (h.direction || "").toUpperCase();
      const dirLabel = dirName === "CALL" ? "ВВЕРХ ↗" : (dirName === "PUT" ? "ВНИЗ ↘" : dirName);
      const timeStr = h.created_at ? new Date(h.created_at).toLocaleTimeString().slice(0, 5) : "--:--";

      const html = `
        <div class="tx-item" style="padding:10px 12px; margin-bottom:6px;">
          <div class="tx-icon ${badgeClass}" style="font-size:14px; width:34px; height:34px;">
            ${icon}
          </div>
          <div class="tx-info">
            <div class="tx-name">${h.pair} · ${dirLabel}</div>
            <div class="tx-date">${strikePrice.toFixed(2)} → ${exitPrice !== null ? exitPrice.toFixed(2) : '--'}</div>
          </div>
          <div style="text-align:right;">
            <div class="tx-amount ${badgeClass}">${badgeText}</div>
            <div class="tx-status" style="font-size:10px;">${timeStr}</div>
          </div>
        </div>
      `;
      container.insertAdjacentHTML("beforeend", html);
    });
  } catch (e) {
    console.error("Binary history error:", e);
  }
}

// ── ФЬЮЧЕРСЫ / КОНТРАКТНАЯ ТОРГОВЛЯ В USDT ──
function setFuturesSide(side) {
  futuresSide = side;
  document.getElementById("futures-btn-long")?.classList.toggle("active", side === "LONG");
  document.getElementById("futures-btn-short")?.classList.toggle("active", side === "SHORT");
  updateFuturesUi();
}

function setFuturesLeverage(lev, el) {
  futuresLeverage = lev;
  document.querySelectorAll("#panel-futures .exp-btn").forEach(b => b.classList.remove("active"));
  if (el) el.classList.add("active");
  calcFuturesSummary();
}

function updateFuturesUi() {
  const isLong = futuresSide === "LONG";
  const btn = document.getElementById("futures-submit-btn");
  if (btn) {
    if (isLong) {
      btn.textContent = `🟢 Открыть LONG (по рынку)`;
      btn.style.background = "linear-gradient(135deg, var(--green), #00b87a)";
      btn.style.color = "#000";
    } else {
      btn.textContent = `🔴 Открыть SHORT (по рынку)`;
      btn.style.background = "linear-gradient(135deg, var(--red), #e62244)";
      btn.style.color = "#fff";
    }
  }

  const uAsset = currentAssets.find(a => a.coin === "USDT");
  const uBal = uAsset ? uAsset.balance : 0;
  const hint = document.getElementById("futures-balance-hint");
  if (hint) hint.textContent = `Доступно: $${uBal.toFixed(2)} USDT`;

  calcFuturesSummary();
}

function setFuturesMax() {
  const uAsset = currentAssets.find(a => a.coin === "USDT");
  const uBal = uAsset ? Math.floor(uAsset.balance) : 0;
  const inp = document.getElementById("futures-margin-input");
  if (inp) inp.value = uBal;
  calcFuturesSummary();
}

function calcFuturesSummary() {
  const margin = parseFloat(document.getElementById("futures-margin-input")?.value) || 0;
  const vol = margin * futuresLeverage;
  const volEl = document.getElementById("futures-calc-volume");
  if (volEl) volEl.textContent = `$${vol.toFixed(2)} USDT (${futuresLeverage}x)`;
}

async function submitFuturesOrder() {
  const margin = parseFloat(document.getElementById("futures-margin-input")?.value);
  if (isNaN(margin) || margin <= 0) {
    showToast("Пожалуйста, введите сумму маржи в USDT", true);
    return;
  }

  const uAsset = currentAssets.find(a => a.coin === "USDT");
  const uBal = uAsset ? uAsset.balance : 0;
  if (margin > uBal) {
    showToast(`Недостаточно USDT. Доступно: $${uBal.toFixed(2)}`, true);
    return;
  }

  try {
    const res = await apiRequest("/api/trading/futures/open", {
      method: "POST",
      body: JSON.stringify({
        pair: selectedTradingPair,
        side: futuresSide,
        margin: margin,
        leverage: futuresLeverage
      })
    });

    if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    showToast(res.message || "✓ Позиция успешно открыта!");

    await loadBalances();
    updateTradingBalanceHints();
    updateFuturesUi();
    await loadActiveFuturesPositions();
    await loadTransactions();
  } catch (e) {
    if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('error');
    showToast("Ошибка открытия позиции: " + e.message, true);
  }
}

async function loadActiveFuturesPositions() {
  try {
    const data = await apiRequest("/api/trading/futures/positions");
    activeFuturesPositions = data.positions || [];
    renderActiveFuturesPositions();
    drawChart();
  } catch (e) {
    console.error("Futures positions error:", e);
  }
}

function renderActiveFuturesPositions() {
  const countEl = document.getElementById("futures-open-count");
  const listEl = document.getElementById("futures-positions-list");
  if (countEl) countEl.textContent = activeFuturesPositions.length;
  if (!listEl) return;

  if (activeFuturesPositions.length === 0) {
    listEl.innerHTML = `<div style="text-align:center; padding:12px; color:var(--muted); font-size:12px;">Открытых позиций нет</div>`;
    return;
  }

  listEl.innerHTML = "";
  activeFuturesPositions.forEach(p => {
    const isLong = p.side === "LONG";
    const currPrice = currentLivePrice > 0 ? currentLivePrice : p.current_price;
    let pnl = 0;
    if (isLong) {
      pnl = (currPrice - p.entry_price) / p.entry_price * p.margin * p.leverage;
    } else {
      pnl = (p.entry_price - currPrice) / p.entry_price * p.margin * p.leverage;
    }
    const roi = (pnl / p.margin) * 100;
    const pnlColor = pnl >= 0 ? "var(--green)" : "var(--red)";
    const pnlSign = pnl >= 0 ? "+" : "";

    const card = `
      <div class="active-bet-card" id="pos-card-${p.id}" style="border:1px solid ${isLong ? 'rgba(0,229,160,0.25)' : 'rgba(255,77,106,0.25)'}; margin-bottom:8px;">
        <div class="abc-top">
          <span class="abc-dir ${isLong ? 'call' : 'put'}">${p.pair} · ${p.side} ${p.leverage}x</span>
          <span style="font-family:'Space Mono', monospace; font-size:13px; font-weight:700; color:${pnlColor};" id="pos-pnl-${p.id}">
            ${pnlSign}$${pnl.toFixed(2)} (${pnlSign}${roi.toFixed(1)}%)
          </span>
        </div>
        <div class="abc-details" style="margin-top:6px;">
          <span>Вход: $${p.entry_price.toFixed(2)}</span>
          <span id="pos-curr-${p.id}">Текущая: $${currPrice.toFixed(2)}</span>
        </div>
        <div class="abc-details" style="margin-top:4px;">
          <span>Маржа: $${p.margin.toFixed(2)} USDT</span>
          <span>Объем: $${(p.margin * p.leverage).toFixed(2)}</span>
        </div>
        <button class="btn-secondary" style="margin-top:8px; padding:7px 0; font-size:12px; font-weight:700; width:100%; border-color:var(--warn); color:var(--warn); border-radius:10px; cursor:pointer;" onclick="closeFuturesPosition(${p.id})">
          ✕ Закрыть по рынку ($${currPrice.toFixed(2)})
        </button>
      </div>
    `;
    listEl.insertAdjacentHTML("beforeend", card);
  });
}

function recalcLiveFuturesPnL() {
  if (!activeFuturesPositions || activeFuturesPositions.length === 0 || currentLivePrice <= 0) return;
  activeFuturesPositions.forEach(p => {
    const isLong = p.side === "LONG";
    let pnl = 0;
    if (isLong) {
      pnl = (currentLivePrice - p.entry_price) / p.entry_price * p.margin * p.leverage;
    } else {
      pnl = (p.entry_price - currentLivePrice) / p.entry_price * p.margin * p.leverage;
    }
    const roi = (pnl / p.margin) * 100;
    const pnlColor = pnl >= 0 ? "var(--green)" : "var(--red)";
    const pnlSign = pnl >= 0 ? "+" : "";

    const pnlEl = document.getElementById(`pos-pnl-${p.id}`);
    if (pnlEl) {
      pnlEl.textContent = `${pnlSign}$${pnl.toFixed(2)} (${pnlSign}${roi.toFixed(1)}%)`;
      pnlEl.style.color = pnlColor;
    }

    const currEl = document.getElementById(`pos-curr-${p.id}`);
    if (currEl) {
      currEl.textContent = `Текущая: $${currentLivePrice.toFixed(2)}`;
    }
  });
}

async function closeFuturesPosition(posId) {
  try {
    const res = await apiRequest("/api/trading/futures/close", {
      method: "POST",
      body: JSON.stringify({ position_id: posId })
    });

    if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    showToast(res.message || "✓ Позиция закрыта!");

    await loadBalances();
    updateTradingBalanceHints();
    updateFuturesUi();
    await loadActiveFuturesPositions();
    await loadFuturesHistory();
    await loadTransactions();
  } catch (e) {
    if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('error');
    showToast("Ошибка закрытия позиции: " + e.message, true);
  }
}

async function loadFuturesHistory() {
  try {
    const data = await apiRequest("/api/trading/futures/history?limit=15");
    const listEl = document.getElementById("futures-history-list");
    if (!listEl) return;

    if (!data.history || data.history.length === 0) {
      listEl.innerHTML = `<div style="text-align:center; padding:10px; color:var(--muted); font-size:11px;">Сделок пока нет</div>`;
      return;
    }

    listEl.innerHTML = "";
    data.history.forEach(h => {
      const isLong = h.side === "LONG";
      const isProfit = (h.pnl || 0) >= 0;
      const badgeClass = isProfit ? "in" : "out";
      const pnlSign = isProfit ? "+" : "";
      const timeStr = h.closed_at ? new Date(h.closed_at).toLocaleTimeString().slice(0, 5) : "";

      const html = `
        <div class="tx-item" style="padding:10px 12px; margin-bottom:6px;">
          <div class="tx-icon ${badgeClass}" style="font-size:14px; width:34px; height:34px;">
            ${isLong ? "↗" : "↘"}
          </div>
          <div class="tx-info">
            <div class="tx-name">${h.pair} · ${h.side} ${h.leverage}x</div>
            <div class="tx-date">Вход: $${h.entry_price?.toFixed(2)} → Выход: $${h.close_price?.toFixed(2)}</div>
          </div>
          <div style="text-align:right;">
            <div class="tx-amount ${badgeClass}">${pnlSign}$${(h.pnl || 0).toFixed(2)}</div>
            <div class="tx-status" style="font-size:10px;">${timeStr}</div>
          </div>
        </div>
      `;
      listEl.insertAdjacentHTML("beforeend", html);
    });
  } catch (e) {
    console.error("Futures history error:", e);
  }
}

function logoutSession() {
  localStorage.clear();
  token = "";
  location.reload();
}

// Запуск при загрузке
document.addEventListener("DOMContentLoaded", init);
