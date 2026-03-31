#!/usr/bin/env python3
"""
Script per verificare una sola chiamata Insights con breakdown (publisher_platform, platform_position)
e che la somma spend per (ad_id, date) coincida con i totali da _merge_insight_rows_by_ad_day (come in sync).

Uso (da directory backend, con DB e .env configurati):
  python scripts/test_meta_insights_placement_breakdown.py --account-id ACCOUNT_NUMERIC_ID

Opzionale:
  --days N   (default 1) finestra end_date = oggi - 1, start_date = end_date - (N-1)
  --dry-run  solo API, nessuna scrittura DB
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import MetaAccount
from services.integrations.meta_marketing import MetaMarketingService
from services.sync.meta_marketing_sync import _merge_insight_rows_by_ad_day
from services.utils.crypto import decrypt_token
from services.utils.timezone import now_rome_naive


def _float_spend(row: dict) -> float:
    try:
        return float(str(row.get("spend", 0) or 0))
    except (TypeError, ValueError):
        return 0.0


def _sum_by_ad_date(rows: list[dict]) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = defaultdict(float)
    for r in rows:
        aid = (r.get("ad_id") or "").strip()
        d = (r.get("date") or "").strip()
        if not aid or not d:
            continue
        out[(aid, d)] += _float_spend(r)
    return dict(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Meta insights placement breakdown")
    parser.add_argument(
        "--account-id",
        required=True,
        help="Meta account ID numerico (colonna meta_accounts.account_id)",
    )
    parser.add_argument("--days", type=int, default=1, help="Numero di giorni (>=1)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Non scrivere nulla; solo chiamate API e report",
    )
    args = parser.parse_args()

    days = max(1, args.days)
    end_d = now_rome_naive().date() - timedelta(days=1)
    start_d = end_d - timedelta(days=days - 1)

    db = SessionLocal()
    try:
        account = (
            db.query(MetaAccount)
            .filter(
                MetaAccount.account_id == str(args.account_id).strip(),
                MetaAccount.is_active == True,
            )
            .first()
        )
        if not account:
            print(f"Account {args.account_id} non trovato o non attivo.")
            return 1

        token = decrypt_token(account.access_token)
        service = MetaMarketingService(access_token=token)
        metrics = [
            "spend",
            "impressions",
            "clicks",
            "ctr",
            "cpc",
            "cpm",
            "actions",
            "action_values",
            "cost_per_action_type",
        ]

        print(f"Account {account.account_id} ({account.name}) | range {start_d} → {end_d}")

        # Una sola chiamata API (allineata alla sync: breakdown + merge per totali)
        rows = service.get_insights(
            account_id=account.account_id,
            level="ad",
            date_preset=None,
            start_date=start_d,
            end_date=end_d,
            fields=metrics,
            breakdowns=["publisher_platform", "platform_position"],
        )
        print(f"Insight rows (con breakdown): {len(rows)}")

        if rows:
            print(f"Sample keys: {list(rows[0].keys())}")
            sample = rows[0]
            print(
                f"Sample publisher_platform={sample.get('publisher_platform')!r} "
                f"platform_position={sample.get('platform_position')!r}"
            )

        merged = _merge_insight_rows_by_ad_day(rows)
        sum_raw = _sum_by_ad_date(rows)
        sum_merged = _sum_by_ad_date(merged)
        all_keys = set(sum_raw.keys()) | set(sum_merged.keys())
        mismatches = []
        for k in sorted(all_keys):
            a = sum_raw.get(k, 0.0)
            b = sum_merged.get(k, 0.0)
            ref = max(a, b, 1e-9)
            if abs(a - b) / ref > 0.005:
                mismatches.append({"k": k, "spend_raw_sum": a, "spend_merged": b})

        if mismatches:
            print(f"⚠️  Merge sanity: {len(mismatches)} chiavi (ad_id,date) con spend raw vs merged oltre 0,5%:")
            for m in mismatches[:10]:
                print(json.dumps(m, default=str))
        else:
            print("✓ Merge sanity: somma righe breakdown = totali aggregati per (ad_id, date).")

        backup_dir = os.path.join(os.path.dirname(__file__), "..", "backups")
        os.makedirs(backup_dir, exist_ok=True)
        ts = now_rome_naive().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(
            backup_dir,
            f"meta_insights_placement_breakdown_{account.account_id}_{ts}.json",
        )
        payload = {
            "account_id": account.account_id,
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
            "breakdown_row_count": len(rows),
            "merged_row_count": len(merged),
            "mismatch_count": len(mismatches),
            "dry_run": args.dry_run,
        }
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"Report salvato: {backup_path}")

        if args.dry_run:
            print("Dry-run: nessuna sync DB.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
