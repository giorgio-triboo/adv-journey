#!/bin/bash
# Eseguire SUL SERVER (dopo SSH) per pulire container e immagini prima di un deploy "come primo deploy".
# I volumi mysql_data e redis_data NON vengono rimossi (il DB resta).
# Uso: ssh ec2-user@performance-adv.docker.aws.trd.local
#      cd /home/ec2-user/dashboard-cliente && bash deploy/scripts/clean-server-for-fresh-deploy.sh

set -e
APP_DIR="${APP_DIR:-/home/ec2-user/dashboard-cliente}"
cd "$APP_DIR"

echo "Fermo stack dashboard-cliente..."
docker compose --project-directory "$APP_DIR" -f deploy/docker-compose.prod.yml -f deploy/docker-compose.bluegreen.yml --env-file "$APP_DIR/.env" down 2>/dev/null || true

echo "Rimuovo immagini app e nginx..."
docker rmi dashboard-cliente-app:latest 2>/dev/null || true
docker rmi $(docker images -q 'dashboard-cliente*') 2>/dev/null || true

echo "Pulizia container e immagini non usate (volumi DB/cache restano)..."
docker container prune -f
docker image prune -af

echo "Fatto. Volumi mysql_data e redis_data preservati. Al prossimo deploy sarà come un primo avvio (build + up)."
