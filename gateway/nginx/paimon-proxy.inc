# Ajustes comunes del proxy inverso hacia las APIs de Paimon.
# Las descargas/inferencias pueden tardar (birefnet tarda minutos), así que los
# timeouts son amplios; las subidas admiten hasta 25 MB.
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
# El portal inyecta la clave compartida (primera de API_KEYS) para que
# "Try it out" funcione sin pegar el token en cada API. "-" = sin clave.
proxy_set_header X-API-Key ${API_KEY};
proxy_connect_timeout 5s;
proxy_send_timeout 600s;
proxy_read_timeout 600s;
