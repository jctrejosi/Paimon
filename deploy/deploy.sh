#!/usr/bin/env bash
# ============================================================
# Despliegue de Paimon (audio, generación y procesamiento de imágenes) desde
# la rama `dev`.
#
# Uso:
#   bash deploy/deploy.sh                 # despliega origin/dev
#   bash deploy/deploy.sh <sha|ref>       # despliega un commit/ref concreto
#   DEPLOY_PATH=/ruta bash deploy/deploy.sh
#
# Las claves de API viven en `paimon/.env` (raíz), que no se versiona: los tres
# compose lo cargan con `env_file: ../.env`.
# ============================================================
set -Eeuo pipefail

ROOT="${DEPLOY_PATH:-/mnt/c/Users/Desarrolo4/Documents/paimon}"
TARGET="${1:-origin/dev}"

log()  { printf '[paimon-deploy] %s\n' "$*"; }
warn() { printf '[paimon-deploy] AVISO: %s\n' "$*" >&2; }
die()  { printf '[paimon-deploy] ERROR: %s\n' "$*" >&2; exit 1; }

cd "$ROOT" 2>/dev/null || die "No existe DEPLOY_PATH=$ROOT"
[[ -f .env ]] || die "Falta $ROOT/.env (API_KEYS compartidas)"
command -v git    >/dev/null || die "git no está instalado"
command -v docker >/dev/null || die "docker no está en PATH"
docker info >/dev/null 2>&1 || die "Docker no responde (revisa systemctl status docker)"

GIT_SSH_KEY="${GIT_SSH_KEY:-/etc/mercaldas/deploy_key}"
if [[ -r "$GIT_SSH_KEY" ]]; then
  export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -i $GIT_SSH_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new}"
fi

git_here() {
  git -c safe.directory="$ROOT" -c core.hooksPath=/nonexistent -C "$ROOT" "$@"
}

log "Repositorio: $ROOT"
log "Objetivo   : $TARGET"

git_here fetch --prune origin '+refs/heads/dev:refs/remotes/origin/dev'
git_here rev-parse --verify --quiet "$TARGET^{commit}" >/dev/null \
  || die "El commit/ref '$TARGET' no existe tras el fetch"

git_here checkout -f -B dev "$TARGET"
COMMIT="$(git_here rev-parse --short=12 HEAD)"
log "Checkout en dev: $COMMIT — $(git_here log -1 --pretty=%s)"

wait_healthy() {
  local name="$1" status=""
  for _ in $(seq 1 120); do
    status="$(docker inspect -f \
      '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      "$name" 2>/dev/null || true)"
    case "$status" in
      healthy) log "$name healthy."; return 0 ;;
      unhealthy|exited|dead)
        docker logs --tail 100 "$name" 2>&1 || true
        die "$name quedó en estado '$status'"
        ;;
    esac
    sleep 5
  done
  docker logs --tail 100 "$name" 2>&1 || true
  die "Timeout esperando $name (último: '${status:-desconocido}')"
}

for dir in audio_processing image_generator image_processing; do
  APP="$ROOT/$dir"
  [[ -f "$APP/docker-compose.yml" ]] || die "Falta $APP/docker-compose.yml"

  COMPOSE=(docker compose --project-directory "$APP" -f "$APP/docker-compose.yml")
  if [[ -f "$APP/docker-compose.edge.yml" ]]; then
    COMPOSE+=(-f "$APP/docker-compose.edge.yml")
  else
    warn "$dir sin docker-compose.edge.yml: no quedará en shared_edge."
  fi

  log "== $dir =="
  "${COMPOSE[@]}" config --quiet || die "docker compose config falló en $dir"

  case "$dir" in
    image_generator) "${COMPOSE[@]}" build api worker ;;
    *)               "${COMPOSE[@]}" build ;;
  esac

  "${COMPOSE[@]}" up -d --pull never
  "${COMPOSE[@]}" ps
done

wait_healthy paimon-audio-processing
wait_healthy paimon-image-api
wait_healthy paimon-image-processing

log "Despliegue completado: $COMMIT"
