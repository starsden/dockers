#!/usr/bin/env bash
set -e

# Скрипт сборки шаблонов контейнеров (выполняется при наличии интернета)
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> [1/3] Сборка шаблона WEB (ctf-template-web)..."
docker build -t ctf-template-web:latest "${BASE_DIR}/templates/web"

echo "==> [2/3] Сборка шаблона FTP (ctf-template-ftp)..."
docker build -t ctf-template-ftp:latest "${BASE_DIR}/templates/ftp"

echo "==> [3/3] Сборка шаблона OS (ctf-template-os)..."
docker build -t ctf-template-os:latest "${BASE_DIR}/templates/os"

echo ""
echo "✅ Все шаблоны успешно собраны!"
docker images | grep ctf-template
