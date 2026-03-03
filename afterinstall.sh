#!/bin/bash
# AfterInstall: deploy cepu-lavorazioni (FastAPI + Celery).
# Build Docker, avvio stack, blue-green opzionale (zero downtime).
# Esecuzione locale: APP_DIR=$(pwd) LOCAL_DEPLOY=1 ./afterinstall.sh

set -e

echo "Starting afterinstall script..."

APP_DIR="${APP_DIR:-/home/ec2-user/cepu-lavorazioni}"
LOCAL_DEPLOY="${LOCAL_DEPLOY:-false}"
cd "$APP_DIR"

# Blue-green: attivo se BLUE_GREEN=true o se esiste deploy/docker-compose.bluegreen.yml
if [ -n "$BLUE_GREEN" ]; then
    USE_BLUE_GREEN="$BLUE_GREEN"
else
    USE_BLUE_GREEN="false"
    [ -f "$APP_DIR/deploy/docker-compose.bluegreen.yml" ] && USE_BLUE_GREEN="true"
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

# Compose: base prod + blue-green se attivo
COMPOSE_FILES="--project-directory $APP_DIR -f deploy/docker-compose.prod.yml"
if [ "$USE_BLUE_GREEN" = "true" ]; then
    COMPOSE_FILES="$COMPOSE_FILES -f deploy/docker-compose.bluegreen.yml"
    echo "✓ Blue-green deploy attivo (zero downtime)"
fi

[ -f "$APP_DIR/.env" ] && COMPOSE_FILES="$COMPOSE_FILES --env-file $APP_DIR/.env"

# Directory deploy
mkdir -p deploy/nginx deploy/scripts

if [ ! -f .env ]; then
    echo "ATTENZIONE: .env non trovato. Copiare .env.example in .env e configurarlo."
    exit 1
fi

echo "=========================================="
echo "DEPLOYMENT"
echo "=========================================="

# Senza blue-green: ferma solo app e worker
if [ "$USE_BLUE_GREEN" != "true" ]; then
    if $DOCKER_CMD ps -a --format "{{.Names}}" 2>/dev/null | grep -qE "cepu-lavorazioni-backend(-blue|-green)?|.*backend-blue|.*backend-green"; then
        echo "Stopping existing application container(s)..."
        $COMPOSE_CMD $COMPOSE_FILES stop backend-blue backend-worker 2>/dev/null || true
        $COMPOSE_CMD $COMPOSE_FILES rm -f backend-blue backend-worker 2>/dev/null || true
    fi
fi

# Con blue-green: ferma solo worker durante deploy
if [ "$USE_BLUE_GREEN" = "true" ]; then
    $COMPOSE_CMD $COMPOSE_FILES stop backend-worker 2>/dev/null || true
fi

# Assicura che db e redis siano in esecuzione
if ! $DOCKER_CMD ps --format "{{.Names}}" 2>/dev/null | grep -qE "cepu-lavorazioni-db|.*-db-"; then
    echo "Starting PostgreSQL and Redis..."
    $COMPOSE_CMD $COMPOSE_FILES up -d db redis
    echo "Waiting for PostgreSQL..."
    sleep 15
fi

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
if [ "$USE_BLUE_GREEN" != "true" ]; then
    for img_id in $($DOCKER_CMD images -q cepu-lavorazioni-app:latest 2>/dev/null); do
        $DOCKER_CMD rmi -f "$img_id" 2>/dev/null || true
    done
fi
$DOCKER_CMD image prune -f 2>/dev/null || true
$DOCKER_CMD volume ls -q 2>/dev/null | while read vol; do
    case "$vol" in
        *postgres_data*|*redis_data*|*nginx_cache*) ;;
        *) $DOCKER_CMD volume rm "$vol" 2>/dev/null || true ;;
    esac
done

# Build immagine
echo "Building Docker image..."
$DOCKER_CMD build -t cepu-lavorazioni-app:latest -f deploy/Dockerfile "$APP_DIR"

# Avvio container
echo "Starting containers..."
if [ "$USE_BLUE_GREEN" = "true" ]; then
    UPSTREAM_CONF="$APP_DIR/deploy/nginx/upstream.conf"
    if [ ! -f "$UPSTREAM_CONF" ]; then
        echo "server backend-blue:8000;" > "$UPSTREAM_CONF"
        echo "server backend-green:8000 backup;" >> "$UPSTREAM_CONF"
    fi

    if [ -f "$UPSTREAM_CONF" ]; then
        LINE=$(grep '^server backend-' "$UPSTREAM_CONF" | grep -v backup | head -1)
        if echo "$LINE" | grep -q "backend-green:8000"; then
            CURRENT_COLOR="green"
            INACTIVE_COLOR="blue"
        else
            CURRENT_COLOR="blue"
            INACTIVE_COLOR="green"
        fi
    else
        CURRENT_COLOR="blue"
        INACTIVE_COLOR="green"
    fi

    BLUE_RUNNING=$($DOCKER_CMD ps -q -f name=backend-blue 2>/dev/null | wc -l)
    GREEN_RUNNING=$($DOCKER_CMD ps -q -f name=backend-green 2>/dev/null | wc -l)
    if [ "$BLUE_RUNNING" -eq 0 ] && [ "$GREEN_RUNNING" -eq 0 ]; then
        echo "Primo deploy blue-green: avvio tutti i container..."
        $COMPOSE_CMD $COMPOSE_FILES up -d
        sleep 10
        TARGET_CONTAINER=$($DOCKER_CMD ps -q -f name=backend-blue | head -1)
        [ -z "$TARGET_CONTAINER" ] && TARGET_CONTAINER=$($DOCKER_CMD ps -q -f name=backend-green | head -1)
        DEPLOYED_COLOR="$CURRENT_COLOR"
    else
        echo "Traffico attuale: $CURRENT_COLOR → deploy su $INACTIVE_COLOR"
        PROFILE_OPT=""
        [ "$INACTIVE_COLOR" = "green" ] && PROFILE_OPT="--profile green"
        $COMPOSE_CMD $COMPOSE_FILES $PROFILE_OPT up -d --force-recreate "backend-$INACTIVE_COLOR"
        echo "Attesa avvio backend-$INACTIVE_COLOR..."
        sleep 10

        echo "Switching traffic to $INACTIVE_COLOR..."
        "$APP_DIR/deploy/scripts/switch-upstream.sh" "$INACTIVE_COLOR" "$APP_DIR"
        TARGET_CONTAINER=$($DOCKER_CMD ps -q -f name=backend-$INACTIVE_COLOR | head -1)

        $COMPOSE_CMD $COMPOSE_FILES up -d --force-recreate "backend-$CURRENT_COLOR" backend-worker 2>/dev/null || true
        sleep 5
        DEPLOYED_COLOR="$INACTIVE_COLOR"
    fi
else
    $COMPOSE_CMD $COMPOSE_FILES up -d --force-recreate backend-blue backend-worker
    TARGET_CONTAINER=$($DOCKER_CMD ps -q -f name=backend-blue | head -1)
    echo "Attesa avvio container..."
    sleep 10
fi

# Migrazioni Alembic sul container attivo
echo "Running Alembic migrations (on $TARGET_CONTAINER)..."
$DOCKER_CMD exec "$TARGET_CONTAINER" alembic upgrade head 2>/dev/null || true

# Pulizia finale
$DOCKER_CMD container prune -f 2>/dev/null || true
$DOCKER_CMD image prune -f 2>/dev/null || true

echo ""
echo "=========================================="
echo "✓ DEPLOYMENT COMPLETED"
echo "=========================================="
if [ "$USE_BLUE_GREEN" = "true" ]; then
    echo "  • Blue-green: traffico su ${DEPLOYED_COLOR:-$CURRENT_COLOR}"
fi
echo "  • App su porta 80 (nginx)"
echo "  • Adminer su porta 18080"
