#!/bin/bash
# AfterInstall: deploy insight-magellano (FastAPI + Celery) in single-stack mode.
# Esecuzione locale: APP_DIR=$(pwd) LOCAL_DEPLOY=1 ./afterinstall.sh

set -e

echo "Starting afterinstall script..."

APP_DIR="${APP_DIR:-/home/ec2-user/insight-magellano}"
LOCAL_DEPLOY="${LOCAL_DEPLOY:-false}"
cd "$APP_DIR"

# Su server: ec2-user nel gruppo docker (docker senza sudo)
if [ "$LOCAL_DEPLOY" != "1" ] && [ "$LOCAL_DEPLOY" != "true" ]; then
    usermod -aG docker ec2-user 2>/dev/null || true
fi

# Comando Docker: su server con ec2-user, in locale diretto
if [ "$LOCAL_DEPLOY" = "1" ] || [ "$LOCAL_DEPLOY" = "true" ]; then
    DOCKER_RUN=""
else
    DOCKER_RUN="sudo -u ec2-user"
fi

# Verifica Docker Compose
if command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker compose"
else
    echo "ERROR: Docker Compose not found"
    exit 1
fi

[ -n "$DOCKER_RUN" ] && COMPOSE_CMD="$DOCKER_RUN $DOCKER_COMPOSE_CMD" || COMPOSE_CMD="$DOCKER_COMPOSE_CMD"
[ -n "$DOCKER_RUN" ] && DOCKER_CMD="$DOCKER_RUN docker" || DOCKER_CMD="docker"

COMPOSE_FILES="--project-directory $APP_DIR -f deploy/docker-compose.prod.yml"

# Unico env ufficiale (locale + produzione): backend/.env
ENV_FILE="$APP_DIR/backend/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "ATTENZIONE: $ENV_FILE non trovato. Crealo da backend/.env.example e configurarlo."
    exit 1
fi
COMPOSE_FILES="$COMPOSE_FILES --env-file $ENV_FILE"

# Directory deploy
mkdir -p deploy/nginx deploy/scripts

echo "=========================================="
echo "DEPLOYMENT (single-stack)"
echo "=========================================="

# Assicura che db e redis siano in esecuzione
echo "Starting PostgreSQL and Redis..."
$COMPOSE_CMD $COMPOSE_FILES up -d db redis
echo "Waiting for PostgreSQL..."
sleep 10

# Pulizia risorse Docker
PRUNE_THRESHOLD="${DOCKER_PRUNE_THRESHOLD:-85}"
DOCKER_ROOT="$($DOCKER_CMD info --format '{{.DockerRootDir}}' 2>/dev/null || echo "/var/lib/docker")"
DISK_PCT="$(df "$DOCKER_ROOT" 2>/dev/null | awk 'NR==2 {gsub(/%/,""); print $5}' || echo 0)"
echo "Cleaning up Docker resources (disk: ${DISK_PCT}%, threshold: ${PRUNE_THRESHOLD}%)..."
if [ "$PRUNE_THRESHOLD" -eq 0 ] || [ "$DISK_PCT" -ge "$PRUNE_THRESHOLD" ]; then
    $DOCKER_CMD builder prune -af 2>/dev/null || true
else
    $DOCKER_CMD builder prune -f 2>/dev/null || true
fi
$DOCKER_CMD container prune -f 2>/dev/null || true
$DOCKER_CMD image prune -f 2>/dev/null || true

# Build immagine
echo "Building Docker image..."
$DOCKER_CMD build -t insight-magellano-app:latest -f deploy/Dockerfile "$APP_DIR"

# Avvio/recreate servizi applicativi
echo "Starting application services..."
$COMPOSE_CMD $COMPOSE_FILES up -d --force-recreate backend backend-worker scheduler nginx
echo "Waiting for backend startup..."
sleep 10

TARGET_CONTAINER=$($DOCKER_CMD ps -q -f name=backend | head -1)
if [ -n "$TARGET_CONTAINER" ]; then
    echo "Running Alembic migrations (on $TARGET_CONTAINER)..."
    $DOCKER_CMD exec "$TARGET_CONTAINER" alembic upgrade head 2>/dev/null || true
fi

# Pulizia finale
$DOCKER_CMD container prune -f 2>/dev/null || true
$DOCKER_CMD image prune -f 2>/dev/null || true
$DOCKER_CMD volume prune -f 2>/dev/null || true

echo ""
echo "=========================================="
echo "✓ DEPLOYMENT COMPLETED"
echo "=========================================="
echo "  • Modalità single-stack attiva"
echo "  • App su porta 3000 (nginx)"
echo "  • Adminer disponibile solo se avviato esplicitamente"
