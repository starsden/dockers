FROM alpine:3.19

RUN apk add --no-cache \
    bash \
    openssh-server \
    curl \
    netcat-openbsd \
    python3 \
    busybox-extras \
    sudo

RUN mkdir -p /challenge /var/run/sshd

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Каталог для монтирования файлов задания и скриптов инициализации (Read-Only)
VOLUME /challenge

EXPOSE 22

ENTRYPOINT ["/entrypoint.sh"]
