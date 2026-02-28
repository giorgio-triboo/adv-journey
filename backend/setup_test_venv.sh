#!/bin/bash
# Script per creare un venv ad hoc per testare Magellano

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/test_venv"

echo "=========================================="
echo "Setup Virtual Environment per Test Magellano"
echo "=========================================="
echo ""

# Rimuovi venv esistente se presente
if [ -d "$VENV_DIR" ]; then
    echo "⚠️  Rimozione venv esistente..."
    rm -rf "$VENV_DIR"
fi

# Crea nuovo venv
echo "📦 Creazione virtual environment..."
python3 -m venv "$VENV_DIR"

# Attiva venv
echo "🔌 Attivazione virtual environment..."
source "$VENV_DIR/bin/activate"

# Aggiorna pip
echo "⬆️  Aggiornamento pip..."
pip install --upgrade pip

# Installa dipendenze
echo "📥 Installazione dipendenze da requirements.txt..."
pip install -r "$SCRIPT_DIR/requirements.txt"

# Installa browser Playwright
echo "🌐 Installazione browser Playwright..."
playwright install chromium

echo ""
echo "=========================================="
echo "✅ Setup completato!"
echo "=========================================="
echo ""
echo "Per attivare il venv, esegui:"
echo "  source $VENV_DIR/bin/activate"
echo ""
echo "Per eseguire il test:"
echo "  python test_magellano_gui.py --campaign 199 --days 1"
echo ""
echo "Per disattivare il venv:"
echo "  deactivate"
echo ""
