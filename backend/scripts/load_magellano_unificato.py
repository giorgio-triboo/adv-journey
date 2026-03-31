#!/usr/bin/env python3
"""
Carica le lead da magellano_export_unificato.csv (arricchito con meta_* ID) nel database.

Supporta --cleanup per rimuovere prima le lead presenti nel CSV.

Uso:
    docker compose exec backend python scripts/load_magellano_unificato.py \\
        --csv exports/magelano-export-0226/magellano_export_unificato_0226.csv

Mapping CSV→DB: intestazioni riconosciute per match normalizzato (spazi, punti, underscore)
e alias espliciti; meta_* da colonne meta_* o da facebook_*_id (export Magellano unificato).
"""
import os
import re
import sys
import csv
import logging
from datetime import datetime

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import SessionLocal
from models import Lead, LeadHistory, MetaMarketingData, StatusCategory
from services.utils.crypto import hash_email_for_meta, hash_phone_for_meta
from services.utils.platforms import normalize_platform

logger = logging.getLogger("scripts.load_magellano_unificato")
logging.basicConfig(level=logging.INFO)

CSV_PATH = os.path.join(PROJECT_ROOT, "exports", "magellano-export", "magellano_export_unificato.csv")


def _cell(val):
    if val is None: return ""
    s = str(val).strip()
    return s if s and s.lower() != "nan" else ""


def _norm_status(status_raw):
    if not status_raw: return "magellano_unknown"
    sl = status_raw.lower().strip()
    if "sent" in sl and ("accept" in sl or "ws" in sl or "email" in sl): return "magellano_sent"
    if "firewall" in sl or "blocked" in sl: return "magellano_firewall"
    if "refused" in sl: return "magellano_refused"
    if "waiting" in sl and "marketing" in sl: return "magellano_waiting"
    return f"magellano_{sl.replace(' ', '_').replace('-', '_')}" if sl else "magellano_unknown"


def _status_category(mag_status):
    return StatusCategory.IN_LAVORAZIONE if mag_status == "magellano_sent" else StatusCategory.RIFIUTATO


def _parse_date(val):
    if not val: return None
    try:
        s = str(val).strip()[:19]
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.date()
    except ValueError:
        try:
            return datetime.strptime(str(val).strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def _norm_fb_id(val):
    if val is None or (isinstance(val, float) and (val != val or val == 0)): return None
    s = str(val).strip()
    if not s or s.lower() == "nan": return None
    if s.upper().startswith("I:"): s = s[2:].strip()
    try: return str(int(float(s)))
    except (ValueError, TypeError): return s if s else None


def _to_str(val):
    if val is None or (isinstance(val, float) and (val != val)): return None
    s = str(val).strip()
    return s if s and s.lower() != "nan" else None


def _normalize_header_key(name: str) -> str:
    """Chiave comparabile: solo lettere/numeri lowercase (Id user, id_user, ID User → iduser)."""
    if not name:
        return ""
    return re.sub(r"[^a-z0-9]", "", (name or "").strip().lower())


def _make_row_getter(row: dict):
    """
    Risolve colonne CSV anche se intestazioni differiscono (spazi vs underscore, maiuscole, punti).
    """

    def get(*keys):
        for k in keys:
            if not k:
                continue
            if k in row:
                return row[k]
            target = _normalize_header_key(k)
            if not target:
                continue
            for orig in row:
                if _normalize_header_key(orig) == target:
                    return row.get(orig)
        return None

    return get


def cleanup_leads(db, magellano_ids: set):
    """Rimuove lead e dipendenze."""
    if not magellano_ids:
        return 0
    leads = db.query(Lead).filter(Lead.magellano_id.in_(magellano_ids)).all()
    ids = [l.id for l in leads]
    if not ids:
        return 0
    db.query(LeadHistory).filter(LeadHistory.lead_id.in_(ids)).delete(synchronize_session=False)
    db.query(MetaMarketingData).filter(MetaMarketingData.lead_id.in_(ids)).delete(synchronize_session=False)
    n = db.query(Lead).filter(Lead.id.in_(ids)).delete(synchronize_session=False)
    return n


def load_csv(csv_path: str, cleanup: bool = False) -> dict:
    stats = {"inserted": 0, "updated": 0, "skipped": 0, "errors": 0, "deleted": 0}
    db = SessionLocal()

    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k.strip().strip("\ufeff"): v for k, v in row.items()})

        if rows:
            hdr = list(rows[0].keys())
            logger.info("CSV: %s colonne. Prime intestazioni: %s", len(hdr), hdr[:25])

        magellano_ids = set()
        for row in rows:
            get = _make_row_getter(row)
            mid = _to_str(get("Id user", "id_user", "User id"))
            if mid:
                try: magellano_ids.add(str(int(float(mid))))
                except ValueError: magellano_ids.add(mid)

        if cleanup:
            n = cleanup_leads(db, magellano_ids)
            db.commit()
            stats["deleted"] = n
            logger.info("Rimosse %s leads", n)

        for idx, row in enumerate(rows):
            get = _make_row_getter(row)
            magellano_id = _to_str(get("Id user", "id_user"))
            if not magellano_id:
                stats["skipped"] += 1
                continue

            external_user_id = f"MAG-{magellano_id}" if not str(magellano_id).startswith("MAG-") else magellano_id
            email_raw = _cell(get("Email"))
            phone_raw = _cell(get("Telephone"))
            email_hash = hash_email_for_meta(email_raw) if email_raw else ""
            phone_hash = hash_phone_for_meta(phone_raw) if phone_raw else ""

            status_raw = _cell(get("Sent status", "sent_status"))
            mag_status = _norm_status(status_raw)
            mag_cat = _status_category(mag_status)
            is_paid = mag_status == "magellano_sent"

            subscr = _parse_date(get("Subscr. date", "Subscr date", "subscr_date"))
            fb_id = _norm_fb_id(get("facebook_id", "Facebook Id", "Facebook id"))

            # meta_*: colonne dirette (merge Meta) oppure ID da export Magellano
            meta_c = _to_str(
                get("meta_campaign_id", "Meta campaign id", "campaign_id")
            ) or _to_str(
                get(
                    "facebook_campaign_name_id",
                    "Facebook campaign name id",
                    "facebook_campaign_id",
                )
            )
            meta_as = _to_str(get("meta_adset_id", "Meta adset id", "adset_id")) or _to_str(
                get("facebook_ad_set_id", "Facebook ad set id", "facebook_adset_id")
            )
            meta_ad = _to_str(get("meta_ad_id", "Meta ad id", "ad_id")) or _to_str(
                get("facebook_ad_name_id", "Facebook ad name id", "facebook_ad_id")
            )

            fb_plat_raw = _to_str(get("facebook_piattaforma"))
            platform_norm = normalize_platform(fb_plat_raw) if fb_plat_raw else None

            try:
                existing = db.query(Lead).filter(Lead.magellano_id == magellano_id).first()
                data = {
                    "brand": _to_str(
                        get("gruppocepu_serviziobrand", "Gruppocepu serviziobrand")
                    ),
                    "msg_id": _to_str(get("gruppocepu_idmessaggio", "Gruppocepu idmessaggio")),
                    "form_id": _to_str(get("gruppocepu_formid", "Gruppocepu formid")),
                    "source": _to_str(get("Source")),
                    "campaign_name": _to_str(get("Campaign")),
                    "magellano_campaign_id": _to_str(get("Id campaign", "id_campaign")),
                    "magellano_status_raw": status_raw or None,
                    "magellano_status": mag_status,
                    "magellano_status_category": mag_cat,
                    "is_paid": is_paid,
                    "facebook_ad_name": _to_str(get("facebook_ad_name")),
                    "facebook_ad_set": _to_str(get("facebook_ad_set")),
                    "facebook_campaign_name": _to_str(get("facebook_campaign_name")),
                    "facebook_id": fb_id,
                    "facebook_piattaforma": fb_plat_raw,
                    "magellano_subscr_date": subscr,
                    "meta_campaign_id": meta_c,
                    "meta_adset_id": meta_as,
                    "meta_ad_id": meta_ad,
                    "platform": platform_norm,
                    "current_status": status_raw or mag_status,
                    "status_category": mag_cat,
                }
                if existing:
                    for k, v in data.items():
                        if v is not None:
                            setattr(existing, k, v)
                    if email_hash: existing.email = email_hash
                    if phone_hash: existing.phone = phone_hash
                    db.flush()
                    stats["updated"] += 1
                else:
                    lead = Lead(
                        magellano_id=magellano_id,
                        external_user_id=external_user_id,
                        email=email_hash,
                        phone=phone_hash,
                        **data,
                    )
                    db.add(lead)
                    db.flush()
                    stats["inserted"] += 1
            except Exception as e:
                logger.exception("Riga %s (magellano_id=%s): %s", idx + 2, magellano_id, e)
                stats["errors"] += 1

        db.commit()
    finally:
        db.close()

    return stats


def load_multiple_csv(csv_paths: list[str], cleanup: bool = False) -> dict:
    """
    Ingestione di più file CSV in un'unica run.
    Restituisce statistiche aggregate.
    """
    aggregate = {"inserted": 0, "updated": 0, "skipped": 0, "errors": 0, "deleted": 0}
    for path in csv_paths:
        logger.info("Inizio ingest Magellano da CSV: %s", path)
        stats = load_csv(path, cleanup=cleanup)
        for k in aggregate:
            aggregate[k] += stats.get(k, 0)
        logger.info(
            "Fine ingest CSV %s: deleted=%s inserted=%s updated=%s skipped=%s errors=%s",
            path,
            stats.get("deleted", 0),
            stats.get("inserted", 0),
            stats.get("updated", 0),
            stats.get("skipped", 0),
            stats.get("errors", 0),
        )
    return aggregate


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--cleanup", action="store_true", help="Rimuovi prima le lead presenti nel CSV")
    p.add_argument(
        "--csv",
        action="append",
        help="Path al CSV (può essere passato più volte). Se omesso, usa il CSV unificato di default.",
    )
    args = p.parse_args()

    csv_paths = args.csv if args.csv else [CSV_PATH]
    for path in csv_paths:
        if not os.path.isfile(path):
            logger.error("File non trovato: %s", path)
            sys.exit(1)

    stats = load_multiple_csv(csv_paths, cleanup=args.cleanup)
    logger.info(
        "Fine ingest multipla: deleted=%s inserted=%s updated=%s skipped=%s errors=%s",
        stats["deleted"],
        stats["inserted"],
        stats["updated"],
        stats["skipped"],
        stats["errors"],
    )
    print(
        f"Deleted: {stats['deleted']}, Inserted: {stats['inserted']}, "
        f"Updated: {stats['updated']}, Skipped: {stats['skipped']}, Errors: {stats['errors']}"
    )


if __name__ == "__main__":
    main()
