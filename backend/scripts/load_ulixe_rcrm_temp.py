#!/usr/bin/env python3
"""
Script per caricare dati RCRM da export Ulixe nella tabella provvisoria ulixe_rcrm_temp.
Uso: python -m scripts.load_ulixe_rcrm_temp

Legge i file in backend/exports/ulixe_temp/rcrm-*.csv
Il periodo è dedotto dal nome file: rcrm-0126 -> 2026-01, rcrm-0226 -> 2026-02
"""
import csv
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import UlixeRcrmTemp


EXPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "exports", "ulixe_temp")


def parse_period_from_filename(filename: str) -> str | None:
    """rcrm-0126 -> 2026-01, rcrm-0226 -> 2026-02"""
    name = os.path.splitext(filename)[0]  # rcrm-0126
    if not name.lower().startswith("rcrm-"):
        return None
    suffix = name[5:]  # 0126 or 0226
    if len(suffix) != 4:
        return None
    try:
        mm = int(suffix[:2])  # 01, 02
        yy = int(suffix[2:])  # 26 -> 2026
        year = 2000 + yy if yy < 100 else yy
        return f"{year}-{mm:02d}"
    except ValueError:
        return None


def load_csv(path: str, period: str, db) -> int:
    """Carica un CSV RCRM. Ritorna numero di righe inserite/aggiornate."""
    count = 0
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=",")
        if "IDMessaggio" not in reader.fieldnames or "RCRM" not in reader.fieldnames:
            print(f"  Skip {path}: colonne IDMessaggio o RCRM mancanti")
            return 0
        for row in reader:
            msg_id = str(row.get("IDMessaggio", "")).strip()
            if not msg_id:
                continue
            try:
                rcrm_val = row.get("RCRM", "0").strip().replace(",", ".").replace(" ", "")
                rcrm_count = int(float(rcrm_val)) if rcrm_val else 0
            except (ValueError, TypeError):
                rcrm_count = 0
            existing = db.query(UlixeRcrmTemp).filter(
                UlixeRcrmTemp.msg_id == msg_id,
                UlixeRcrmTemp.period == period,
            ).first()
            if existing:
                existing.rcrm_count = rcrm_count
                existing.source_file = os.path.basename(path)
                count += 1
            else:
                rec = UlixeRcrmTemp(
                    msg_id=msg_id,
                    period=period,
                    rcrm_count=rcrm_count,
                    source_file=os.path.basename(path),
                )
                db.add(rec)
                count += 1
    return count


def main():
    if not os.path.isdir(EXPORTS_DIR):
        print(f"Directory non trovata: {EXPORTS_DIR}")
        sys.exit(1)
    db = SessionLocal()
    try:
        files = [f for f in os.listdir(EXPORTS_DIR) if f.lower().startswith("rcrm-") and f.lower().endswith(".csv")]
        if not files:
            print(f"Nessun file rcrm-*.csv in {EXPORTS_DIR}")
            sys.exit(0)
        total = 0
        for filename in sorted(files):
            period = parse_period_from_filename(filename)
            if not period:
                print(f"Skip {filename}: periodo non riconosciuto")
                continue
            path = os.path.join(EXPORTS_DIR, filename)
            n = load_csv(path, period, db)
            total += n
            print(f"  {filename} -> {period}: {n} righe")
        db.commit()
        print(f"Totale: {total} righe caricate/aggiornate")
    finally:
        db.close()


if __name__ == "__main__":
    main()
