#!/bin/bash
#
# Migra il database locale in produzione (sostituisce i dati in prod con quelli locali).
# Uso: ./scripts/migrate_db_to_production.sh
#
# Richiede:
#   - Docker locale (per dump da db)
#   - SSH access a PROD_HOST
#
set -e

PROD_HOST="${PROD_HOST:-ec2-user@magellano-insight.docker.aws.trd.local}"
DUMP_FILE="db_migrate_$(date +%Y%m%d_%H%M%S).sql"
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

echo "=========================================="
echo "Migrazione DB locale → Produzione"
echo "=========================================="
echo "  Host produzione: $PROD_HOST"
echo "  File dump: $DUMP_FILE"
echo ""

# 1. Dump database locale
echo "1. Dump database locale..."
cd "$APP_DIR"
if docker compose ps db 2>/dev/null | grep -q Up; then
    docker compose exec -T db pg_dump -U user -d cepudb --clean --if-exists --no-owner --no-acl > "$DUMP_FILE"
elif docker compose -f docker-compose.yml ps db 2>/dev/null | grep -q Up; then
    docker compose -f docker-compose.yml exec -T db pg_dump -U user -d cepudb --clean --if-exists --no-owner --no-acl > "$DUMP_FILE"
else
    echo "ERRORE: Container db non in esecuzione. Avvia con: docker compose up -d db"
    exit 1
fi

SIZE=$(wc -c < "$DUMP_FILE")
echo "   ✓ Dump completato ($(echo $SIZE | awk '{printf "%.1f MB", $1/1024/1024}'))"
echo ""

# 2. Copia dump sul server
echo "2. Copia dump su $PROD_HOST..."
scp "$DUMP_FILE" "$PROD_HOST:/tmp/$DUMP_FILE"
echo "   ✓ File copiato"
echo ""

# 3. Restore in produzione
echo "3. Restore in produzione (sostituisce dati esistenti)..."
echo "   ATTENZIONE: i dati attuali in produzione saranno sostituiti."
if [[ "$1" != "-y" && "$1" != "--yes" ]]; then
    read -p "   Continuare? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[yY]$ ]]; then
        echo "Operazione annullata."
        rm -f "$DUMP_FILE"
        exit 0
    fi
fi

# Restaura: ferma backend per evitare lock, restaura, riavvia
ssh "$PROD_HOST" 'cd /home/ec2-user/insight-magellano && \
    echo "   Fermando backend..." && \
    sudo -u ec2-user docker compose -f deploy/docker-compose.prod.yml --profile green stop backend-blue backend-green backend-worker 2>/dev/null || true && \
    sleep 2 && \
    U=$(grep -E "^POSTGRES_USER=" .env 2>/dev/null | cut -d= -f2- || echo "user"); \
    P=$(grep -E "^POSTGRES_PASSWORD=" .env 2>/dev/null | cut -d= -f2-); \
    [ -z "$P" ] && P=$(grep DATABASE_URL .env 2>/dev/null | sed -n "s|.*://[^:]*:\([^@]*\)@.*|\1|p"); \
    [ -z "$P" ] && P=password; \
    D=$(grep -E "^POSTGRES_DB=" .env 2>/dev/null | cut -d= -f2- || echo "cepudb"); \
    export PGPASSWORD="$P"; \
    echo "   Restore in corso..." && \
    cat /tmp/'"$DUMP_FILE"' | docker exec -i insight-magellano-db-1 psql -h localhost -U "$U" -d "$D" --set ON_ERROR_STOP=on -q && \
    rm -f /tmp/'"$DUMP_FILE"' && \
    echo "   Riavviando backend..." && \
    sudo -u ec2-user docker compose -f deploy/docker-compose.prod.yml --profile green start backend-blue backend-green backend-worker && \
    echo "Restore completato"'

echo ""
echo "4. Pulizia file locale..."
rm -f "$DUMP_FILE"
echo "   ✓ File locale rimosso"
echo ""
echo "=========================================="
echo "✓ Migrazione completata"
echo "=========================================="
echo "Database produzione aggiornato con i dati locali."
echo ""
