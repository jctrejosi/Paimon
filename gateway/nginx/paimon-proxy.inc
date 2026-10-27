# Ajustes comunes del proxy inverso hacia las APIs de Paimon.
# Las descargas/inferencias pueden tardar (birefnet tarda minutos), así que los
# timeouts son amplios; las subidas admiten hasta 25 MB.
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-API-Key $paimon_api_key;
proxy_connect_timeout 5s;
proxy_send_timeout 600s;
proxy_read_timeout 600s;
