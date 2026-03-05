#!/bin/bash
# Esegue sync Magellano in locale con browser VISIBILE.
# Le date sono nello stesso formato del frontend (YYYY-MM-DD).
#
# Uso:
#   ./scripts/run_magellano_local.sh
#   ./scripts/run_magellano_local.sh --start 2026-03-01 --end 2026-03-03
#   ./scripts/run_magellano_local.sh 2026-03-01 2026-03-03

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$BACKEND_DIR/test_venv"

if [ ! -d "$VENV" ]; then
    echo "Creo venv con: bash setup_test_venv.sh"
    cd "$BACKEND_DIR" && bash setup_test_venv.sh
fi

# DB locale (Docker espone 5432)
export DATABASE_URL="${DATABASE_URL:-postgresql://user:password@localhost:5432/cepudb}"

cd "$BACKEND_DIR"
source "$VENV/bin/activate"

# Se passati 2 argomenti posizionali, usali come start/end
if [ $# -eq 2 ]; then
    exec python scripts/run_magellano_local.py --start "$1" --end "$2"
else
    exec python scripts/run_magellano_local.py "$@"
fi
