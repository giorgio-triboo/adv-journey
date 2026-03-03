#!/bin/bash
# Diagnostica sul server: eseguire come root o ec2-user dopo SSH.
# Uso: sudo bash deploy/scripts/server-debug.sh

set -e
APP_DIR="${APP_DIR:-/home/ec2-user/dashboard-cliente}"
cd "$APP_DIR"
COMPOSE_OPTS="--project-directory $APP_DIR -f deploy/docker-compose.prod.yml -f deploy/docker-compose.bluegreen.yml --env-file $APP_DIR/.env"

echo "=== 1. Tutti i container (anche fermati) ==="
docker ps -a

echo ""
echo "=== 2. Servizi del progetto compose (dashboard-cliente) ==="
docker compose $COMPOSE_OPTS ps -a 2>/dev/null || true

echo ""
echo "=== 3. Immagine dashboard-cliente-app esiste? ==="
docker images dashboard-cliente-app:latest 2>/dev/null || true

echo ""
echo "=== 4. .env presente? ==="
test -f .env && echo "Sì" || echo "NO - obbligatorio per compose"

echo ""
echo "=== 5. Ultimi log CodeDeploy (AfterInstall) ==="
if [ -d /opt/codedeploy-agent/deployment-root ]; then
  LATEST=$(ls -t /opt/codedeploy-agent/deployment-root/ 2>/dev/null | head -1)
  if [ -n "$LATEST" ]; then
    echo "Deploy id: $LATEST"
    cat /opt/codedeploy-agent/deployment-root/"$LATEST"/deployment-archive/afterinstall.log 2>/dev/null || \
    cat /opt/codedeploy-agent/deployment-root/"$LATEST"/logs/scripts.log 2>/dev/null || \
    echo "Log non trovato in path standard"
  fi
fi

echo ""
echo "=== 6. Avvio stack (dry-run / pull) ==="
docker compose $COMPOSE_OPTS config 2>&1 | head -30

echo ""
echo "=== 7. Prova avvio (se fallisce vedi errore sotto) ==="
docker compose $COMPOSE_OPTS up -d 2>&1

echo ""
echo "=== 8. Stato dopo up ==="
docker compose $COMPOSE_OPTS ps -a

echo ""
echo "=== 9. Log nginx (ultime 30 righe) ==="
docker compose $COMPOSE_OPTS logs --tail=30 nginx 2>/dev/null || true

echo ""
echo "=== 10. Log app-blue (ultime 20 righe) ==="
docker compose $COMPOSE_OPTS logs --tail=20 app-blue 2>/dev/null || true
