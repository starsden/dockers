FROM alpine:3.19

RUN apk add --no-cache vsftpd bash

RUN mkdir -p /var/ftp/pub /var/run/vsftpd

COPY vsftpd.conf /etc/vsftpd/vsftpd.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Каталог для монтирования файлов задания с хоста (Read-Only)
VOLUME /var/ftp/pub

EXPOSE 21

ENTRYPOINT ["/entrypoint.sh"]
