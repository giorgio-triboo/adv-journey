#!/bin/bash
# Switch traffico blue <-> green. Ricarica nginx.
# Uso: ./deploy/scripts/switch-upstream.sh blue|green [APP_DIR]
# Chiamato da afterinstall.sh durante deploy blue-green.

set -e
ACTIVE="${1:-blue}"
APP_DIR="${2:-$(cd "$(dirname "$0")/../.." && pwd)}"

if [[ "$ACTIVE" != "blue" && "$ACTIVE" != "green" ]]; then
  echo "Uso: $0 blue|green [APP_DIR]"
  exit 1
fi

UPSTREAM_CONF="$APP_DIR/deploy/nginx/upstream.conf"
if [[ ! -f "$UPSTREAM_CONF" ]]; then
  echo "Errore: $UPSTREAM_CONF non trovato."
  exit 1
fi

if [[ "$ACTIVE" == "blue" ]]; then
  echo "server backend-blue:8000;"  > "$UPSTREAM_CONF"
  echo "server backend-green:8000 backup;" >> "$UPSTREAM_CONF"
else
  echo "server backend-green:8000;"  > "$UPSTREAM_CONF"
  echo "server backend-blue:8000 backup;" >> "$UPSTREAM_CONF"
fi

# Trova container nginx (nome dipende dal project compose)
NGINX_CONTAINER=$(docker ps -q -f "name=nginx" | head -1)
if [[ -n "$NGINX_CONTAINER" ]]; then
  docker exec "$NGINX_CONTAINER" nginx -s reload 2>/dev/null || true
  echo "Traffico su istanza: $ACTIVE"
else
  echo "Container nginx non trovato. Rilancia lo stack."
  exit 1
fi
