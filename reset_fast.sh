#!/bin/bash

# Script per reset rapido: ricostruire database senza rimontare Docker
# Salta la ricostruzione delle immagini Docker per risparmiare tempo

set -e  # Exit on error

echo "⚡ Reset rapido del sistema (senza ricostruire Docker)..."
echo ""

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Fermare tutti i container
echo -e "${YELLOW}1. Fermando i container...${NC}"
docker-compose down -v || true
echo -e "${GREEN}✓ Container fermati${NC}"
echo ""

# 2. Rimuovere il volume del database per reset completo
echo -e "${YELLOW}2. Rimuovendo il volume del database...${NC}"
docker volume rm adj-journey_postgres_data 2>/dev/null || true
echo -e "${GREEN}✓ Volume database rimosso${NC}"
echo ""

# 3. Avviare i container (usando immagini esistenti)
echo -e "${YELLOW}3. Avviando i container (immagini esistenti)...${NC}"
docker-compose up -d
echo -e "${GREEN}✓ Container avviati${NC}"
echo ""

# 4. Attendere che il database sia pronto
echo -e "${YELLOW}4. Attendendo che il database sia pronto...${NC}"
sleep 5
for i in {1..30}; do
    if docker-compose exec -T db pg_isready -U user > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Database pronto${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}✗ Timeout: database non pronto dopo 30 secondi${NC}"
        exit 1
    fi
    sleep 1
done
echo ""

# 5. Eseguire le migration da zero (PRIMA di avviare l'app che potrebbe creare tabelle)
echo -e "${YELLOW}5. Eseguendo le migration del database...${NC}"
# Assicurati che la tabella alembic_version esista
docker-compose exec -T db psql -U user -d cepudb -c "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num));" 2>/dev/null || true
# Verifica che ci sia solo una head revision
HEADS=$(docker-compose exec -T backend alembic heads 2>/dev/null | wc -l | tr -d ' ')
if [ "$HEADS" -gt 1 ]; then
    echo -e "${RED}✗ Errore: Multiple head revisions trovate. Risolvi il conflitto prima di continuare.${NC}"
    docker-compose exec -T backend alembic heads
    exit 1
fi
# Esegui le migrazioni
docker-compose exec -T backend alembic upgrade head
echo -e "${GREEN}✓ Migration completate${NC}"
echo ""

# 6. Eseguire i seeder (campaigns, traffic_platforms, msg_mapping, users, thresholds, alerts)
echo -e "${YELLOW}6. Eseguendo i seeder...${NC}"
docker-compose exec -T backend python3 -c "
from seeders.campaigns_seeder import seed_campaigns
from seeders.traffic_platforms_seeder import seed_traffic_platforms
from seeders.msg_traffic_mapping_seeder import seed_msg_traffic_mapping
from seeders.users_seeder import seed_users
from seeders.marketing_threshold_config_seeder import seed_marketing_threshold_config
from seeders.alert_config_seeder import seed_alert_configs
seed_campaigns()
seed_traffic_platforms()
seed_msg_traffic_mapping()
seed_users()
seed_marketing_threshold_config()
seed_alert_configs()
"
echo -e "${GREEN}✓ Seeder completati${NC}"
echo ""

# 7. Pulire token OAuth Meta dal database (se esistono)
echo -e "${YELLOW}7. Pulendo token OAuth Meta dal database...${NC}"
docker-compose exec -T backend python3 scripts/clean_oauth_tokens.py 2>/dev/null || echo "Nessun token da pulire (database nuovo)"
echo -e "${GREEN}✓ Token OAuth puliti${NC}"
echo ""

# 8. Verificare che tutto funzioni
echo -e "${YELLOW}8. Verificando lo stato dei container...${NC}"
docker-compose ps
echo ""

echo -e "${GREEN}✅ Reset rapido terminato con successo!${NC}"
echo ""
echo "📝 Note:"
echo "  - Database completamente resettato (tutti i dati sono stati eliminati)"
echo "  - Immagini Docker NON ricostruite (risparmio di tempo)"
echo "  - Sessioni utente e cache OAuth Meta sono state pulite"
echo "  - Tutte le migration sono state eseguite da zero"
echo "  - Seeder (campaigns, platforms, msg_mapping, users, thresholds, alerts) eseguiti"
echo ""
echo "🚀 Il sistema è pronto per essere testato!"
echo "   Accesso: http://localhost:8003"
echo ""
echo "💡 Per un reset completo con ricostruzione Docker, usa: ./reset_all.sh"
