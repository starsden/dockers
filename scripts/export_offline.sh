#!/usr/bin/env bash
set -e

# Экспорт собранных образов в tar-архив для переноса на изолированный сервер
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIVE_PATH="${BASE_DIR}/ctf_templates_offline.tar"

echo "==> Экспорт образов в архив: ${ARCHIVE_PATH}..."
docker save -o "${ARCHIVE_PATH}" \
    ctf-template-web:latest \
    ctf-template-ftp:latest \
    ctf-template-os:latest

echo "✅ Образы успешно экспортированы!"
echo "Размер архива: $(du -h "${ARCHIVE_PATH}" | cut -f1)"
echo "Скопируйте этот файл на целевой сервер и выполните scripts/import_offline.sh"
