#!/usr/bin/env bash
# Allinea l'ambiente locale alla produzione: installa backend/requirements.txt in .venv (repo root).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Creo .venv in ${ROOT} ..."
  python3 -m venv .venv
fi

echo "Installo dipendenze da backend/requirements.txt (come nel Dockerfile) ..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r backend/requirements.txt

echo ""
echo "OK. Per avviare l'API senza Docker:"
echo "  cd backend && ../.venv/bin/python -m uvicorn main:app --reload --host 0.0.0.0 --port 8003"
echo ""
echo "Oppure: source .venv/bin/activate && cd backend && uvicorn main:app --reload --port 8003"
