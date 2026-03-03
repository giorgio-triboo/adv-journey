#!/bin/bash

# Script per reset completo: ricostruire immagini, database e pulire cache

set -e  # Exit on error

echo "🔄 Reset completo del sistema..."
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

# 2. Rimuovere le immagini
echo -e "${YELLOW}2. Rimuovendo le immagini Docker...${NC}"
docker-compose rm -f || true
docker rmi $(docker images | grep -E "adj-journey|backend" | awk '{print $3}') 2>/dev/null || true
echo -e "${GREEN}✓ Immagini rimosse${NC}"
echo ""

# 3. Rimuovere il volume del database per reset completo
echo -e "${YELLOW}3. Rimuovendo il volume del database...${NC}"
docker volume rm adj-journey_postgres_data 2>/dev/null || true
echo -e "${GREEN}✓ Volume database rimosso${NC}"
echo ""

# 4. Pulire build cache Docker (opzionale ma consigliato)
echo -e "${YELLOW}4. Pulendo la cache di build Docker...${NC}"
docker builder prune -f || true
echo -e "${GREEN}✓ Cache build pulita${NC}"
echo ""

# 5. Ricostruire le immagini da zero
echo -e "${YELLOW}5. Ricostruendo le immagini Docker (no cache)...${NC}"
docker-compose build --no-cache
echo -e "${GREEN}✓ Immagini ricostruite${NC}"
echo ""

# 6. Avviare i container
echo -e "${YELLOW}6. Avviando i container...${NC}"
docker-compose up -d
echo -e "${GREEN}✓ Container avviati${NC}"
echo ""

# 7. Attendere che il database sia pronto
echo -e "${YELLOW}7. Attendendo che il database sia pronto...${NC}"
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

# 8. Eseguire le migration da zero
echo -e "${YELLOW}8. Eseguendo le migration del database...${NC}"
docker-compose exec -T backend alembic upgrade head
echo -e "${GREEN}✓ Migration completate${NC}"
echo ""

# 9. Eseguire i seeder (campaigns, users)
echo -e "${YELLOW}9. Eseguendo i seeder (campaigns, users)...${NC}"
docker-compose exec -T backend python3 -c "
from seeders.campaigns_seeder import seed_campaigns
seed_campaigns()
from seeders.users_seeder import seed_users
seed_users()
"
echo -e "${GREEN}✓ Seeder completati${NC}"
echo ""

# 10. Pulire token OAuth Meta dal database (se esistono)
echo -e "${YELLOW}10. Pulendo token OAuth Meta dal database...${NC}"
docker-compose exec -T backend python3 scripts/clean_oauth_tokens.py 2>/dev/null || echo "Nessun token da pulire (database nuovo)"
echo -e "${GREEN}✓ Token OAuth puliti${NC}"
echo ""

# 11. Verificare che tutto funzioni
echo -e "${YELLOW}11. Verificando lo stato dei container...${NC}"
docker-compose ps
echo ""

echo -e "${GREEN}✅ Reset completo terminato con successo!${NC}"
echo ""
echo "📝 Note:"
echo "  - Database completamente resettato (tutti i dati sono stati eliminati)"
echo "  - Immagini Docker ricostruite da zero"
echo "  - Sessioni utente e cache OAuth Meta sono state pulite"
echo "  - Tutte le migration sono state eseguite da zero"
echo "  - Seeder (campaigns, users) eseguiti"
echo ""
echo "🚀 Il sistema è pronto per essere testato!"
echo "   Accesso: http://localhost:8003"
