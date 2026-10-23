# syntax=docker/dockerfile:1

# Portal Swagger global de Paimon: una sola UI que agrupa las APIs de
# audio_processing, image_generator e image_processing.
#
# nginx sirve Swagger UI y hace de proxy inverso hacia las APIs publicadas en
# 127.0.0.1 del host, de modo que todas comparten origen (sin CORS y con
# "Try it out" funcionando).
FROM nginx:1.27-alpine

ARG SWAGGER_UI_VERSION=5.17.14

# Swagger UI se sirve desde el propio contenedor (sin CDN, local-first).
RUN apk add --no-cache curl \
    && mkdir -p /usr/share/nginx/html \
    && curl -sSL "https://registry.npmjs.org/swagger-ui-dist/-/swagger-ui-dist-${SWAGGER_UI_VERSION}.tgz" \
        | tar xz -C /tmp \
    && cp -r /tmp/package/. /usr/share/nginx/html/ \
    && rm -rf /tmp/package \
    && apk del curl

COPY html/index.html /usr/share/nginx/html/index.html
COPY nginx/paimon-proxy.inc /etc/nginx/paimon-proxy.inc
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 8080

# El comando por defecto de la imagen nginx procesa /etc/nginx/templates/*.template
# con envsubst y arranca nginx.
