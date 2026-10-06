FROM alpine:3.19

RUN apk add --no-cache nginx

# Создаем рабочие каталоги для nginx
RUN mkdir -p /run/nginx /var/www/html

COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Каталог для монтирования контента задания с хоста (Read-Only)
VOLUME /var/www/html

EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
