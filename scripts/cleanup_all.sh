#!/usr/bin/env bash

# Скрипт экстренной/ручной очистки всех запущенных контейнеров заданий
echo "==> Поиск и остановка активных контейнеров заданий CTF..."
CONTAINERS=$(docker ps -a --filter "name=ctf_" -q)

if [ -n "$CONTAINERS" ]; then
    docker rm -f $CONTAINERS
    echo "✅ Все контейнеры заданий остановлены и удалены."
else
    echo "ℹ️ Активных контейнеров заданий не обнаружено."
fi
