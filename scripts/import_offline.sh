#!/usr/bin/env bash
set -e

# Импорт образов на изолированном сервере без подключения к сети Интернет
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIVE_PATH="${BASE_DIR}/ctf_templates_offline.tar"

if [ ! -f "${ARCHIVE_PATH}" ]; then
    echo "❌ Ошибка: Архив ${ARCHIVE_PATH} не найден!"
    exit 1
fi

echo "==> Загрузка образов из офлайн-архива: ${ARCHIVE_PATH}..."
docker load -i "${ARCHIVE_PATH}"

echo "✅ Образы успешно импортированы в локальный Docker!"
docker images | grep ctf-template
