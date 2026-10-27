# gateway — Swagger global de Paimon

Un único portal que reúne las APIs de Paimon en **un solo origen**:

| Prefijo | API | Destino |
|---------|-----|---------|
| `/audio/` | `audio_processing` | `127.0.0.1:<AUDIO_PORT>` |
| `/image/` | `image_generator` | `127.0.0.1:<IMAGE_PORT>` |
| `/processing/` | `image_processing` (remove-bg) | `127.0.0.1:<PROCESSING_PORT>` |
| `/voice/` | `audio_generator` (texto→voz) | `127.0.0.1:<VOICE_PORT>` |

Abre `http://localhost:8080` y elige la API en el selector de arriba a la derecha.

## Cómo funciona

- **nginx** sirve Swagger UI (assets locales, sin CDN) y hace de **proxy inverso**
  hacia las APIs publicadas en el loopback del host.
- Al compartir origen, no hacen falta reglas CORS y el botón *Try it out*
  funciona directamente sobre `/audio`, `/image`, `/processing` y `/voice`.
- Corre con `network_mode: host` y escucha solo en `127.0.0.1`, así que no se
  expone a la LAN. Node `dev.js` elige un puerto libre (`8080` por defecto) y le
  pasa los puertos reales de cada API: no hay puertos fijos que mantener.
- El portal **inyecta la primera clave de `API_KEYS`** (del `.env` de la raíz)
  como cabecera `X-API-Key`, de modo que Swagger funciona sin pegar el token en
  cada API. Sin `.env`, envía `-` (clave inválida).
- El índice solo muestra las APIs que responden: si un servicio está parado, su
  tarjeta desaparece en lugar de mostrar un error.

## Ejecución

```bash
# portal + la API de quita-fondo
node dev.js --swagger --processing

# solo el portal (proxyecta lo que ya esté corriendo)
node dev.js --swagger

# todo (apps + portal)
node dev.js
```

Aliases del flag: `--docs`, `--gateway`, `--portal`.

El flag de la API de voz es `--voice` (alias `--tts`, `--text-to-speech`,
`--audio-generator`).

Prueba directa contra el proxy (sin clave: la inyecta nginx):

```bash
curl -s -F file=@foto.jpg http://localhost:8080/processing/remove-bg -o sin-fondo.png
```

## Añadir otra API

1. Añade un `location /nueva/` en `nginx/default.conf.template` con
   `proxy_pass http://127.0.0.1:${NUEVA_PORT}/;`.
2. Añade el puerto en `docker-compose.yml` (`NUEVA_PORT`) y en `dev.js`
   (`GATEWAY_TARGETS`).
3. Añade la entrada a la lista `SERVICES` de `html/index.html`.
4. Reconstruye: `node dev.js --swagger --build`.
