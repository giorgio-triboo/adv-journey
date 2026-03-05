#!/bin/bash
# ApplicationStop: ferma solo il worker (insight-magellano). Backend restano up per zero-downtime.

set -e

# CodeDeploy esegue gli hook dalla directory di deploy (destination in appspec)
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)}"
APP_DIR="${APP_DIR:-/home/ec2-user/insight-magellano}"
cd "$APP_DIR"

if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
else
    echo "Docker Compose not found, skipping stop"
    exit 0
fi

# Su server EC2: esegui come ec2-user
if [ -z "$LOCAL_DEPLOY" ] || [ "$LOCAL_DEPLOY" != "1" ]; then
    COMPOSE_CMD="sudo -u ec2-user $COMPOSE_CMD"
fi

COMPOSE_OPTS="--project-directory $APP_DIR -f deploy/docker-compose.prod.yml"
[ -f "$APP_DIR/.env" ] && COMPOSE_OPTS="$COMPOSE_OPTS --env-file $APP_DIR/.env"

# Ferma SOLO il worker. Non toccare backend-blue/backend-green: nginx continua a servire traffico.
# AfterInstall farà lo switch blue/green e ricreerà il worker con la nuova immagine.
echo "Stopping insight-magellano backend-worker only (backends stay up for zero-downtime)..."
$COMPOSE_CMD $COMPOSE_OPTS stop backend-worker 2>/dev/null || true

echo "Stop completed."
