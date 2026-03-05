#!/bin/bash
# Avvia lo stack insight-magellano sul server (dopo SSH).
# Esegui: sudo bash deploy/scripts/start-stack.sh
# oppure: APP_DIR=/path/to/insight-magellano ./deploy/scripts/start-stack.sh

set -e
APP_DIR="${APP_DIR:-/home/ec2-user/insight-magellano}"
cd "$APP_DIR"

if [[ ! -f .env ]]; then
  echo "ERRORE: .env non trovato in $APP_DIR"
  exit 1
fi

COMPOSE_OPTS="--project-directory $APP_DIR -f deploy/docker-compose.prod.yml --env-file $APP_DIR/.env"

# Blue-green: aggiungi overlay e profile se necessario
if [[ -f deploy/docker-compose.bluegreen.yml ]]; then
  COMPOSE_OPTS="$COMPOSE_OPTS -f deploy/docker-compose.bluegreen.yml"
fi

mkdir -p deploy/nginx deploy/scripts

echo "Avvio stack insight-magellano..."
set -a
source .env 2>/dev/null || true
set +a
docker compose $COMPOSE_OPTS up -d

echo "Attesa avvio servizi (15s)..."
sleep 15

echo ""
echo "=== Container in esecuzione ==="
docker compose $COMPOSE_OPTS ps -a

echo ""
echo "=== Log nginx (ultime 15 righe) ==="
docker compose $COMPOSE_OPTS logs --tail=15 nginx 2>/dev/null || true

echo ""
echo "App su http://localhost:3000 - Adminer su http://localhost:18080"
