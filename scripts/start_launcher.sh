#!/usr/bin/env bash
set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Проверка наличия Python 3 и Docker
command -v python3 >/dev/null 2>&1 || { echo "❌ Ошибка: python3 не установлен"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "❌ Ошибка: docker не установлен"; exit 1; }

echo "==> Запуск CTF Task Launcher..."
cd "${BASE_DIR}"
exec python3 launcher/server.py
