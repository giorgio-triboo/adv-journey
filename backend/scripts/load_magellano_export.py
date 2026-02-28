"""
Carica le lead dal CSV di export Magellano (magellano-user-export.csv) nel database.

Formato CSV atteso: email, id_facebook, telephone, facebook_ad_name_id, facebook_ad_set_id,
facebook_campaign_name_id, facebook_id

Uso (da root progetto, con backend avviato):
    docker compose exec backend python scripts/load_magellano_export.py [path_csv]

Se path_csv non è fornito, usa docs/data_export/magellano-user-export.csv (path relativo alla repo).
"""

import os
import sys
import csv
import logging
import argparse
from pathlib import Path

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
REPO_ROOT = os.path.dirname(PROJECT_ROOT)  # cepu-lavorazioni
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import SessionLocal
from models import Lead, StatusCategory
# Email e telefono vanno salvati come hash SHA256 (specifiche Meta Conversion API)
from services.utils.crypto import hash_email_for_meta, hash_phone_for_meta

logger = logging.getLogger("scripts.load_magellano_export")
logging.basicConfig(level=logging.INFO)


def _cell(value):
    if value is None:
        return ""
    s = str(value).strip()
    return s if s else ""


def load_magellano_export(csv_path: str, dry_run: bool = False) -> dict:
    """
    Legge il CSV Magellano e inserisce/aggiorna le lead nel DB.

    Returns:
        dict con chiavi: inserted, updated, skipped, errors
    """
    stats = {"inserted": 0, "updated": 0, "skipped": 0, "errors": 0}
    db = SessionLocal()
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                logger.error("CSV vuoto o senza intestazione")
                return stats
            # Normalizza nomi colonne (lowercase, strip)
            fieldnames = [c.strip().lower() for c in reader.fieldnames]
            rows = list(reader)

        for idx, row in enumerate(rows):
            # Supporta sia "email" che "Email" etc.
            row_lower = {k.strip().lower(): v for k, v in row.items()}
            email_raw = _cell(row_lower.get("email"))
            id_facebook = _cell(row_lower.get("id_facebook"))
            telephone = _cell(row_lower.get("telephone"))
            facebook_ad_name_id = _cell(row_lower.get("facebook_ad_name_id"))
            facebook_ad_set_id = _cell(row_lower.get("facebook_ad_set_id"))
            facebook_campaign_name_id = _cell(row_lower.get("facebook_campaign_name_id"))
            facebook_id = _cell(row_lower.get("facebook_id"))

            if not email_raw and not id_facebook:
                stats["skipped"] += 1
                continue

            # magellano_id univoco: preferiamo id_facebook, altrimenti generato
            if id_facebook:
                magellano_id = id_facebook
            else:
                magellano_id = f"MAG-IMP-{idx}"

            external_user_id = f"MAG-{magellano_id}" if not magellano_id.startswith("MAG-") else magellano_id
            # Salvataggio come hash SHA256 (normalizzazione + hash per Meta)
            email_hash = hash_email_for_meta(email_raw) if email_raw else ""
            phone_hash = hash_phone_for_meta(telephone) if telephone else ""

            # facebook_id: colonna facebook_id o id_facebook
            fb_id = facebook_id or id_facebook

            if dry_run:
                stats["inserted"] += 1
                continue

            try:
                existing = db.query(Lead).filter(Lead.magellano_id == magellano_id).first()
                if existing:
                    # Aggiorna campi da CSV (email/phone hash, meta ids, facebook_id)
                    if email_hash:
                        existing.email = email_hash
                    if phone_hash:
                        existing.phone = phone_hash
                    if fb_id:
                        existing.facebook_id = fb_id
                    if facebook_ad_name_id:
                        existing.meta_ad_id = facebook_ad_name_id
                    if facebook_ad_set_id:
                        existing.meta_adset_id = facebook_ad_set_id
                    if facebook_campaign_name_id:
                        existing.meta_campaign_id = facebook_campaign_name_id
                    db.flush()
                    stats["updated"] += 1
                else:
                    new_lead = Lead(
                        magellano_id=magellano_id,
                        external_user_id=external_user_id,
                        email=email_hash,
                        phone=phone_hash,
                        facebook_id=fb_id or None,
                        meta_ad_id=facebook_ad_name_id or None,
                        meta_adset_id=facebook_ad_set_id or None,
                        meta_campaign_id=facebook_campaign_name_id or None,
                        status_category=StatusCategory.IN_LAVORAZIONE,
                        current_status="imported_magellano_export",
                    )
                    db.add(new_lead)
                    stats["inserted"] += 1
            except Exception as e:
                logger.exception("Riga %s (magellano_id=%s): %s", idx + 2, magellano_id, e)
                stats["errors"] += 1

        if not dry_run:
            db.commit()
    finally:
        db.close()

    return stats


def main():
    parser = argparse.ArgumentParser(description="Carica lead da CSV export Magellano nel DB")
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=os.path.join(REPO_ROOT, "docs", "data_export", "magellano-user-export.csv"),
        help="Percorso al file CSV (default: docs/data_export/magellano-user-export.csv)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Non scrivere su DB, solo conta")
    args = parser.parse_args()

    path = os.path.abspath(args.csv_path)
    if not os.path.isfile(path):
        logger.error("File non trovato: %s", path)
        sys.exit(1)

    logger.info("Caricamento da %s (dry_run=%s)", path, args.dry_run)
    stats = load_magellano_export(path, dry_run=args.dry_run)
    logger.info(
        "Fine: inserted=%s updated=%s skipped=%s errors=%s",
        stats["inserted"],
        stats["updated"],
        stats["skipped"],
        stats["errors"],
    )
    print(f"Inserted: {stats['inserted']}, Updated: {stats['updated']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}")


if __name__ == "__main__":
    main()
