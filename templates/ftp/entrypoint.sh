#!/bin/bash
set -e

PORT="${FTP_PORT:-21}"
PASV_PORT="${FTP_PASV_PORT:-21000}"
HOST_IP="${HOST_IP:-127.0.0.1}"
ANON_ENABLE="${FTP_ANON_ENABLE:-YES}"
USERNAME="${FTP_USER:-ctfuser}"
PASSWORD="${FTP_PASS:-ctfpassword}"

# Настройка портов и IP в конфиге
sed -i "s/__FTP_PORT__/${PORT}/g" /etc/vsftpd/vsftpd.conf
sed -i "s/__PASV_PORT__/${PASV_PORT}/g" /etc/vsftpd/vsftpd.conf
sed -i "s/__HOST_IP__/${HOST_IP}/g" /etc/vsftpd/vsftpd.conf
sed -i "s/anonymous_enable=.*/anonymous_enable=${ANON_ENABLE}/g" /etc/vsftpd/vsftpd.conf

# Если анонимный вход отключен, создаем пользователя
if [ "$ANON_ENABLE" != "YES" ]; then
    if ! id -u "$USERNAME" >/dev/null 2>&1; then
        adduser -D -h /var/ftp/pub -s /bin/false "$USERNAME"
        echo "${USERNAME}:${PASSWORD}" | chpasswd
    fi
fi

# Проверяем права на каталог
chown -R root:root /var/ftp
chmod 755 /var/ftp
chmod -R 755 /var/ftp/pub

echo "[FTP TEMPLATE] Запуск vsftpd на порту ${PORT} (pasv port: ${PASV_PORT})..."
exec /usr/sbin/vsftpd /etc/vsftpd/vsftpd.conf
