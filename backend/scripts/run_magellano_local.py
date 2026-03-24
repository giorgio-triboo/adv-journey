#!/usr/bin/env python3
"""
Script standalone per testare sync Magellano in locale con browser VISIBILE.
Usa le stesse date che arrivano dal frontend (formato YYYY-MM-DD).
Evita import da services.api.ui per compatibilità Python 3.9.

Uso (dal Mac, con venv attivo):
  cd backend && source test_venv/bin/activate
  DATABASE_URL="postgresql://user:password@localhost:5432/cepudb" python scripts/run_magellano_local.py
  DATABASE_URL="postgresql://user:password@localhost:5432/cepudb" python scripts/run_magellano_local.py --start 2026-03-01 --end 2026-03-03 --campaign 190
  python scripts/run_magellano_local.py --headless  # senza finestra browser
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configura logging prima di altri import
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("magellano_local")

# Import minimi (compatibili Python 3.9)
from database import SessionLocal
from models import Lead, StatusCategory
from services.utils.crypto import hash_email_for_meta, hash_phone_for_meta
from services.integrations.magellano import MagellanoService
from services.integrations.lead_correlation import LeadCorrelationService


def run_sync(db, campaigns: list, start_date: date, end_date: date, headless: bool = False) -> None:
    """Logica di ingest Magellano usata per test locale, senza dipendenze UI."""
    service = MagellanoService(headless=headless)
    correlation_service = LeadCorrelationService()

    logger.info("Fetching leads: campaigns=%s, date %s to %s", campaigns, start_date, end_date)
    leads_data = service.fetch_leads(start_date, end_date, campaigns)
    logger.info("Fetched %d leads from Magellano", len(leads_data))

    if leads_data:
        dates_count = Counter(d.get("magellano_subscr_date") for d in leads_data if d.get("magellano_subscr_date"))
        logger.info("Distribuzione date nell'export: %s", dict(sorted(dates_count.items())))

    new_leads = []
    for data in leads_data:
        magellano_id = data.get("magellano_id")
        existing = db.query(Lead).filter(Lead.magellano_id == magellano_id).first()

        magellano_status_raw = data.get("magellano_status_raw") or data.get("status_raw")
        magellano_status = data.get("magellano_status")
        magellano_status_category = data.get("magellano_status_category")
        current_status = magellano_status_raw if magellano_status_raw else magellano_status
        status_category = magellano_status_category if magellano_status_category else StatusCategory.UNKNOWN

        if not existing:
            new_lead = Lead(
                magellano_id=magellano_id,
                external_user_id=data.get("external_user_id"),
                email=hash_email_for_meta(data.get("email", "")),
                phone=hash_phone_for_meta(data.get("phone", "")),
                brand=data.get("brand"),
                msg_id=data.get("msg_id"),
                form_id=data.get("form_id"),
                source=data.get("source"),
                campaign_name=data.get("campaign_name"),
                magellano_campaign_id=data.get("magellano_campaign_id"),
                magellano_subscr_date=data.get("magellano_subscr_date"),
                magellano_status_raw=magellano_status_raw,
                magellano_status=magellano_status,
                magellano_status_category=magellano_status_category,
                payout_status=data.get("payout_status"),
                is_paid=data.get("is_paid", False),
                facebook_ad_name=data.get("facebook_ad_name"),
                facebook_ad_set=data.get("facebook_ad_set"),
                facebook_campaign_name=data.get("facebook_campaign_name"),
                facebook_id=data.get("facebook_id"),
                facebook_piattaforma=data.get("facebook_piattaforma"),
                current_status=current_status,
                status_category=status_category,
            )
            db.add(new_lead)
            new_leads.append(new_lead)
        else:
            if magellano_status_raw:
                existing.magellano_status_raw = magellano_status_raw
            if magellano_status:
                existing.magellano_status = magellano_status
            if magellano_status_category:
                existing.magellano_status_category = magellano_status_category
            if not existing.ulixe_status:
                existing.current_status = current_status
                existing.status_category = status_category
            if "payout_status" in data:
                existing.payout_status = data.get("payout_status")
            if "is_paid" in data:
                existing.is_paid = data.get("is_paid", False)
            for k in ("campaign_name", "facebook_ad_name", "facebook_ad_set", "facebook_campaign_name", "facebook_id"):
                if data.get(k):
                    setattr(existing, k, data[k])

    db.commit()
    if new_leads:
        stats = correlation_service.correlate_batch(new_leads, db)
        logger.info("Lead Correlation: %s correlated, %s not found", stats["correlated"], stats["not_found"])


def main():
    parser = argparse.ArgumentParser(description="Sync Magellano in locale con browser visibile")
    parser.add_argument("--start", default=None, help="Data inizio YYYY-MM-DD (come dal frontend)")
    parser.add_argument("--end", default=None, help="Data fine YYYY-MM-DD (come dal frontend)")
    parser.add_argument("--campaign", type=int, default=190, help="ID campagna Magellano")
    parser.add_argument("--headless", action="store_true", help="Browser headless (senza finestra)")
    args = parser.parse_args()

    today = date.today()
    start_date = datetime.strptime(args.start, "%Y-%m-%d").date() if args.start else today - timedelta(days=7)
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else today

    print("=" * 60)
    print("Magellano Sync - Test Locale (date come dal frontend)")
    print("=" * 60)
    print(f"  Periodo:     {start_date} → {end_date}  (formato YYYY-MM-DD)")
    print(f"  Campagna:    {args.campaign}")
    print(f"  Browser:    {'headless' if args.headless else 'VISIBILE (puoi monitorare)'}")
    print("=" * 60)

    db = SessionLocal()
    try:
        run_sync(db, [args.campaign], start_date, end_date, headless=args.headless)
        print("\nSync completato. Dati salvati in DB.")
    except Exception as e:
        logger.exception("Sync fallito: %s", e)
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
