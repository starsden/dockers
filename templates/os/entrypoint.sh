#!/bin/bash
set -e

SSH_PORT="${SSH_PORT:-22}"
USERNAME="${OS_USER:-ctfuser}"
PASSWORD="${OS_PASS:-ctfpassword}"

# Генерация ключей хоста SSH если отсутствуют
ssh-keygen -A

# Создаем пользователя если не существует
if ! id -u "$USERNAME" >/dev/null 2>&1; then
    adduser -D -s /bin/bash "$USERNAME"
    echo "${USERNAME}:${PASSWORD}" | chpasswd
    echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
fi

# Если в задании передан кастомный скрипт инициализации
if [ -f "/challenge/init.sh" ]; then
    echo "[OS TEMPLATE] Выполнение /challenge/init.sh..."
    bash /challenge/init.sh &
fi

# Настройка порта SSH
sed -i "s/#Port 22/Port ${SSH_PORT}/g" /etc/ssh/sshd_config
sed -i "s/Port 22/Port ${SSH_PORT}/g" /etc/ssh/sshd_config

echo "[OS TEMPLATE] Запуск SSH-сервера на порту ${SSH_PORT}..."
exec /usr/sbin/sshd -D -e
