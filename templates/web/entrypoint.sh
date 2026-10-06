#!/bin/sh
set -e

# Порт веб-сервера внутри контейнера (по умолчанию 80)
PORT="${WEB_PORT:-80}"

# Подставляем порт в конфигурацию nginx
sed -i "s/__WEB_PORT__/${PORT}/g" /etc/nginx/nginx.conf

echo "[WEB TEMPLATE] Тестирование конфигурации..."
/usr/sbin/nginx -t

echo "[WEB TEMPLATE] Запуск Nginx на порту ${PORT}..."
exec /usr/sbin/nginx
