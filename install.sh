#!/usr/bin/env bash
# ==============================================================================
#  ⚡ VAULT CRYPTO WALLET — ALL-IN-ONE INSTALLER & DEPLOYMENT SCRIPT ⚡
#  Мультивалютный криптокошелек с WebApp в Telegram, панелью администратора (GOD)
#  и поддержкой 10 популярных криптовалют.
# ==============================================================================

set -e

# Цвета для вывода в консоль
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Очистка экрана и приветственный баннер
clear
echo -e "${CYAN}${BOLD}"
echo "  ██╗   ██╗ █████╗ ██╗   ██╗██╗  ████████╗"
echo "  ██║   ██║██╔══██╗██║   ██║██║  ╚══██╔══╝"
echo "  ██║   ██║███████║██║   ██║██║     ██║   "
echo "  ╚██╗ ██╔╝██╔══██║██║   ██║██║     ██║   "
echo "   ╚████╔╝ ██║  ██║╚██████╔╝███████╗██║   "
echo "    ╚═══╝  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝   "
echo -e "${NC}"
echo -e "${YELLOW}${BOLD}  === Telegram Crypto Wallet & Admin GOD Panel Installer ===${NC}\n"

# 1. Проверка прав суперпользователя (root)
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[!] Этот скрипт должен быть запущен с правами root (sudo bash install.sh)${NC}"
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo -e "${BLUE}[*] Рабочая директория:${NC} $PROJECT_DIR"

# 2. Интерактивный опрос пользователя
echo -e "\n${PURPLE}${BOLD}--- Шаг 1: Конфигурация приложения ---${NC}\n"

# Wallet / Platform Name
read -rp "$(echo -e "${CYAN}1. Введите название кошелька [Vault]: ${NC}")" PROJECT_NAME
PROJECT_NAME=${PROJECT_NAME:-Vault}

# Telegram Bot Token
while true; do
  read -rp "$(echo -e "${CYAN}2. Введите Telegram Bot Token (от @BotFather): ${NC}")" BOT_TOKEN
  BOT_TOKEN=$(echo "$BOT_TOKEN" | tr -d '[:space:]')
  if [ -n "$BOT_TOKEN" ]; then
    break
  else
    echo -e "${RED}Токен бота не может быть пустым!${NC}"
  fi
done

# Admin Telegram ID
while true; do
  read -rp "$(echo -e "${CYAN}3. Введите ваш Telegram User ID (из @userinfobot): ${NC}")" ADMIN_IDS
  ADMIN_IDS=$(echo "$ADMIN_IDS" | tr -d '[:space:]')
  if [ -n "$ADMIN_IDS" ]; then
    break
  else
    echo -e "${RED}Telegram ID обязателен для доступа к админ-панели!${NC}"
  fi
done

# Admin Password
read -rp "$(echo -e "${CYAN}4. Задайте пароль для входа в веб-панель администратора [admin12345]: ${NC}")" ADMIN_PASSWORD
ADMIN_PASSWORD=${ADMIN_PASSWORD:-admin12345}

# Server Port
read -rp "$(echo -e "${CYAN}5. Порт внутреннего сервера FastAPI [8000]: ${NC}")" SERVER_PORT
SERVER_PORT=${SERVER_PORT:-8000}

# Domain / WebApp URL
echo -e "\n${YELLOW}[!] Внимание: Telegram WebApp требует обязательный HTTPS протокол!${NC}"
read -rp "$(echo -e "${CYAN}6. Введите ваш домен (например, wallet.mydomain.com) или оставьте пустым: ${NC}")" DOMAIN_NAME
DOMAIN_NAME=$(echo "$DOMAIN_NAME" | tr -d '[:space:]')

SETUP_NGINX=false
WEBAPP_URL="http://localhost:$SERVER_PORT"

if [ -n "$DOMAIN_NAME" ]; then
  WEBAPP_URL="https://$DOMAIN_NAME"
  SETUP_NGINX=true
  read -rp "$(echo -e "${CYAN}   Email для SSL сертификата Let's Encrypt [admin@${DOMAIN_NAME}]: ${NC}")" SSL_EMAIL
  SSL_EMAIL=${SSL_EMAIL:-admin@${DOMAIN_NAME}}
else
  echo -e "${YELLOW}Домен не указан. Вы сможете настроить HTTPS позже через Cloudflare Tunnel или reverse proxy.${NC}"
fi

# Генерация секретного ключа
SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "vault-secret-key-$(date +%s)")

# 3. Установка системных зависимостей
echo -e "\n${PURPLE}${BOLD}--- Шаг 2: Установка системных пакетов ---${NC}\n"
apt-get update -y
apt-get install -y python3 python3-pip python3-venv git curl openssl

if [ "$SETUP_NGINX" = true ]; then
  apt-get install -y nginx certbot python3-certbot-nginx
fi

# 4. Создание .env файла
echo -e "\n${PURPLE}${BOLD}--- Шаг 3: Сохранение настроек (.env) ---${NC}\n"
cat > "$PROJECT_DIR/.env" <<EOF
PROJECT_NAME=${PROJECT_NAME}
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=${ADMIN_IDS}
SECRET_KEY=${SECRET_KEY}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
HOST=0.0.0.0
PORT=${SERVER_PORT}
WEBAPP_URL=${WEBAPP_URL}
DATABASE_PATH=${PROJECT_DIR}/vault.db
EOF

chmod 600 "$PROJECT_DIR/.env"
echo -e "${GREEN}[✓] Файл конфигурации .env успешно сохранен.${NC}"

# 5. Создание виртуального окружения Python и установка библиотек
echo -e "\n${PURPLE}${BOLD}--- Шаг 4: Настройка виртуального окружения Python ---${NC}\n"
if [ ! -d "$PROJECT_DIR/venv" ]; then
  python3 -m venv "$PROJECT_DIR/venv"
fi

"$PROJECT_DIR/venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
echo -e "${GREEN}[✓] Все зависимости Python успешно установлены.${NC}"

# 6. Настройка Nginx и SSL (если выбран домен)
if [ "$SETUP_NGINX" = true ] && [ -n "$DOMAIN_NAME" ]; then
  echo -e "\n${PURPLE}${BOLD}--- Шаг 5: Настройка веб-сервера Nginx и SSL ---${NC}\n"
  
  # Очищаем старые и конфликтующие сайты (включая default и сайты от других сервисов)
  rm -f /etc/nginx/sites-enabled/*

  # Проверяем, существует ли уже SSL-сертификат Let's Encrypt для этого домена
  if [ -f "/etc/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem" ]; then
    echo -e "${GREEN}[✓] Обнаружен существующий SSL-сертификат для ${DOMAIN_NAME}.${NC}"
    cat > "/etc/nginx/sites-available/crypto-vault" <<EOF
server {
    server_name ${DOMAIN_NAME};

    location / {
        proxy_pass http://127.0.0.1:${SERVER_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN_NAME}/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}

server {
    listen 80;
    server_name ${DOMAIN_NAME};
    return 301 https://\$host\$request_uri;
}
EOF
  else
    cat > "/etc/nginx/sites-available/crypto-vault" <<EOF
server {
    listen 80;
    server_name ${DOMAIN_NAME};

    location / {
        proxy_pass http://127.0.0.1:${SERVER_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  fi

  ln -sf /etc/nginx/sites-available/crypto-vault /etc/nginx/sites-enabled/crypto-vault
  nginx -t && systemctl restart nginx

  if [ ! -f "/etc/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem" ]; then
    echo -e "${CYAN}Получение бесплатного SSL сертификата от Let's Encrypt...${NC}"
    certbot --nginx -d "$DOMAIN_NAME" --non-interactive --agree-tos -m "$SSL_EMAIL" --redirect || {
      echo -e "${YELLOW}[!] Не удалось автоматически выпустить SSL. Убедитесь, что DNS запись домена указывает на IP этого сервера.${NC}"
    }
    nginx -t && systemctl restart nginx
  fi
  echo -e "${GREEN}[✓] Nginx и HTTPS успешно настроены для https://${DOMAIN_NAME}${NC}"
fi

# 7. Настройка службы systemd (автозапуск 24/7)
echo -e "\n${PURPLE}${BOLD}--- Шаг 6: Настройка системной службы systemd ---${NC}\n"

SERVICE_FILE="/etc/systemd/system/crypto-vault.service"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Vault Crypto Telegram Bot & WebApp Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=${PROJECT_DIR}/.env
ExecStart=${PROJECT_DIR}/venv/bin/python ${PROJECT_DIR}/run.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable crypto-vault
systemctl restart crypto-vault
echo -e "${GREEN}[✓] Служба crypto-vault активирована и запущена.${NC}"

# 8. Создание вспомогательных скриптов управления
cat > "$PROJECT_DIR/start.sh" << 'EOF'
#!/usr/bin/env bash
systemctl start crypto-vault
echo "Служба crypto-vault запущена."
EOF

cat > "$PROJECT_DIR/stop.sh" << 'EOF'
#!/usr/bin/env bash
systemctl stop crypto-vault
echo "Служба crypto-vault остановлена."
EOF

cat > "$PROJECT_DIR/restart.sh" << 'EOF'
#!/usr/bin/env bash
systemctl restart crypto-vault
echo "Служба crypto-vault перезапущена."
EOF

cat > "$PROJECT_DIR/status.sh" << 'EOF'
#!/usr/bin/env bash
systemctl status crypto-vault
EOF

cat > "$PROJECT_DIR/logs.sh" << 'EOF'
#!/usr/bin/env bash
journalctl -u crypto-vault -f -n 100
EOF

chmod +x "$PROJECT_DIR/start.sh" "$PROJECT_DIR/stop.sh" "$PROJECT_DIR/restart.sh" "$PROJECT_DIR/status.sh" "$PROJECT_DIR/logs.sh"

# 9. Финальный отчет и инструкции
echo -e "\n${GREEN}${BOLD}================================================================${NC}"
echo -e "${GREEN}${BOLD}        🎉 УСТАНОВКА VAULT УСПЕШНО ЗАВЕРШЕНА! 🎉       ${NC}"
echo -e "${GREEN}${BOLD}================================================================${NC}\n"

echo -e "📌 ${BOLD}Параметры вашей системы:${NC}"
echo -e "   • WebApp URL (клиент): ${CYAN}${WEBAPP_URL}${NC}"
echo -e "   • Панель Администратора: ${CYAN}${WEBAPP_URL}/admin${NC}"
echo -e "   • Пароль администратора: ${YELLOW}${ADMIN_PASSWORD}${NC}"
echo -e "   • Telegram ID админа:    ${YELLOW}${ADMIN_IDS}${NC}"
echo -e "   • База данных SQLite:   ${PROJECT_DIR}/vault.db\n"

echo -e "⚙️ ${BOLD}Команды управления службой:${NC}"
echo -e "   • Проверка статуса:   ${CYAN}./status.sh${NC}  или  systemctl status crypto-vault"
echo -e "   • Просмотр логов:     ${CYAN}./logs.sh${NC}    или  journalctl -u crypto-vault -f"
echo -e "   • Перезапуск:         ${CYAN}./restart.sh${NC}"
echo -e "   • Остановка:          ${CYAN}./stop.sh${NC}\n"

echo -e "📱 ${BOLD}Как подключить WebApp в Telegram через @BotFather:${NC}"
echo -e "   1. Откройте диалог с ${CYAN}@BotFather${NC} в Telegram."
echo -e "   2. Отправьте команду: ${YELLOW}/setmenubutton${NC}"
echo -e "   3. Выберите вашего созданного бота."
echo -e "   4. Отправьте URL WebApp: ${CYAN}${WEBAPP_URL}${NC}"
echo -e "   5. Введите название кнопки: ${YELLOW}⚡ Кошелёк${NC}\n"

echo -e "🚀 ${BOLD}Готово! Откройте вашего бота в Telegram и напишите /start${NC}\n"
