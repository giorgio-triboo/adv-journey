#!/usr/bin/env python3
"""
Test end-to-end: targeting reale da Meta → confronto prima/dopo enrich_targeting_custom_audience_names.

Usa il token dell'account collegato in DB (meta_accounts). Richiede DATABASE_URL e .env coerenti.

Uso (root repo, con Docker):
  docker compose run --rm backend python scripts/test_meta_custom_audience_enrich_e2e.py --account-id NUMERIC_ID

Con ad set noto (meno chiamate, niente scan campagne):
  docker compose run --rm backend python scripts/test_meta_custom_audience_enrich_e2e.py \\
    --account-id NUMERIC_ID --adset-id ADSET_GRAPH_ID

Con campagna nota:
  --campaign-id CAMPAIGN_GRAPH_ID

Exit code:
  0 — validazione ok (nomi risolti dove mancavano, o già presenti e invariati)
  1 — errore API / account non trovato / ad set non trovato
  2 — nessuna Custom Audience nel targeting nell'ambito scansionato (non si può validare l'enrich)
  3 — almeno un id senza name resta vuoto dopo enrich (permessi o oggetto non leggibile)
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import MetaAccount
from services.integrations.meta_marketing import MetaMarketingService
from services.utils.crypto import decrypt_token
from services.utils.timezone import now_rome_naive

from facebook_business.adobjects.adaccount import AdAccount


def collect_custom_audience_entries(targeting: dict[str, Any]) -> list[dict[str, str]]:
    """Estrae voci {scope, id, name} da custom_audiences / excluded_custom_audiences (anche annidate)."""
    out: list[dict[str, str]] = []

    def walk_list(items: Any, scope: str) -> None:
        if not isinstance(items, list):
            return
        for it in items:
            if not isinstance(it, dict):
                continue
            raw_id = it.get("id")
            if raw_id is None:
                continue
            sid = str(raw_id).strip()
            if not sid:
                continue
            name = (it.get("name") or "").strip()
            out.append({"scope": scope, "id": sid, "name": name})

    for key in ("custom_audiences", "excluded_custom_audiences"):
        walk_list(targeting.get(key), f"targeting.{key}")

    flex = targeting.get("flexible_spec")
    if isinstance(flex, list):
        for i, block in enumerate(flex):
            if not isinstance(block, dict):
                continue
            for key in ("custom_audiences", "excluded_custom_audiences"):
                walk_list(block.get(key), f"flexible_spec[{i}].{key}")
            excl = block.get("exclusions")
            if isinstance(excl, dict):
                for key in ("custom_audiences", "excluded_custom_audiences"):
                    walk_list(excl.get(key), f"flexible_spec[{i}].exclusions.{key}")

    return out


def _pick_adset_from_campaigns(
    service: MetaMarketingService,
    account_id: str,
    max_campaigns: int,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Scansiona le prime max_campaigns campagne e restituisce il primo ad set il cui targeting
    contiene almeno una custom_audiences / excluded_custom_audiences.
    """
    account = AdAccount(f"act_{account_id}")
    try:
        campaigns = service._make_api_call_with_retry(
            lambda: list(account.get_campaigns(fields=["id", "name"]))
        )
    except Exception as e:
        return None, f"Errore elenco campagne: {e}"

    for camp in campaigns[:max_campaigns]:
        cid = camp.get("id")
        if not cid:
            continue
        adsets = service.get_adsets(str(cid), enrich_custom_audience_names=False)
        for a in adsets:
            t = a.get("targeting") or {}
            if isinstance(t, dict) and collect_custom_audience_entries(t):
                return a, None
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="E2E: arricchimento nomi Custom Audience su targeting Meta reale",
    )
    parser.add_argument(
        "--account-id",
        required=True,
        help="ID numerico ad account (meta_accounts.account_id, senza act_)",
    )
    parser.add_argument("--adset-id", help="ID Graph dell'ad set (consigliato per test mirato)")
    parser.add_argument("--campaign-id", help="ID Graph campagna (alternativa allo scan)")
    parser.add_argument(
        "--max-campaigns",
        type=int,
        default=25,
        help="Campagne da scansionare se non passi adset/campaign (default 25)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        account = (
            db.query(MetaAccount)
            .filter(
                MetaAccount.account_id == str(args.account_id).strip(),
                MetaAccount.is_active == True,  # noqa: E712
            )
            .first()
        )
        if not account:
            print(f"Account {args.account_id} non trovato o non attivo nel DB.", file=sys.stderr)
            return 1

        token = decrypt_token(account.access_token)
        service = MetaMarketingService(access_token=token)

        chosen: dict[str, Any] | None = None

        if args.adset_id:
            chosen = service.get_adset_snapshot(
                str(args.adset_id).strip(),
                enrich_custom_audience_names=False,
            )
            if not chosen:
                print(f"Ad set {args.adset_id} non recuperabile da Meta.", file=sys.stderr)
                return 1
        elif args.campaign_id:
            adsets = service.get_adsets(
                str(args.campaign_id).strip(),
                enrich_custom_audience_names=False,
            )
            for a in adsets:
                t = a.get("targeting") or {}
                if isinstance(t, dict) and collect_custom_audience_entries(t):
                    chosen = a
                    break
            if not chosen and adsets:
                chosen = adsets[0]
            if not chosen:
                print("Nessun ad set nella campagna indicata.", file=sys.stderr)
                return 1
        else:
            chosen, scan_err = _pick_adset_from_campaigns(
                service,
                str(args.account_id).strip(),
                max_campaigns=max(1, args.max_campaigns),
            )
            if scan_err:
                print(scan_err, file=sys.stderr)
                return 1

        if not chosen:
            print(
                f"Nessun ad set con Custom Audience nel targeting "
                f"(prime {args.max_campaigns} campagne). Usa --adset-id o --campaign-id.",
                file=sys.stderr,
            )
            return 2

        raw_targeting = chosen.get("targeting") or {}
        if not isinstance(raw_targeting, dict):
            print("Targeting non è un dict dopo normalizzazione.", file=sys.stderr)
            return 1

        before_rows = collect_custom_audience_entries(raw_targeting)
        if not before_rows:
            print(
                "Questo ad set non ha voci custom_audiences / excluded_custom_audiences nel targeting: "
                "non è possibile validare l'enrich su questo esempio.",
                file=sys.stderr,
            )
            return 2

        raw_copy = copy.deepcopy(raw_targeting)
        enriched = service.enrich_targeting_custom_audience_names(raw_copy)
        after_rows = collect_custom_audience_entries(enriched)

        # Indice per confronto (scope + id)
        def key(r: dict[str, str]) -> tuple[str, str]:
            return (r["scope"], r["id"])

        after_by_key = {key(r): r for r in after_rows}

        print(
            f"Account {account.account_id} ({account.name or ''}) | "
            f"ad set {chosen.get('adset_id')} — {chosen.get('name', '')!r}"
        )
        print("")
        print(f"Voci Custom Audience trovate: {len(before_rows)}")
        print("")

        need_resolve = [r for r in before_rows if not r["name"]]
        had_names = [r for r in before_rows if r["name"]]

        for r in before_rows:
            aft = after_by_key.get(key(r), {"name": ""})
            print(
                f"  scope={r['scope']}\n"
                f"    id:  {r['id']}\n"
                f"    prima name:  {r['name']!r}\n"
                f"    dopo name:   {aft.get('name', '')!r}\n"
            )

        backup_dir = os.path.join(os.path.dirname(__file__), "..", "backups")
        os.makedirs(backup_dir, exist_ok=True)
        ts = now_rome_naive().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(
            backup_dir,
            f"meta_ca_enrich_e2e_{account.account_id}_{chosen.get('adset_id')}_{ts}.json",
        )
        payload = {
            "account_id": account.account_id,
            "adset_id": chosen.get("adset_id"),
            "adset_name": chosen.get("name", ""),
            "targeting_before_enrich": copy.deepcopy(raw_targeting),
            "targeting_after_enrich": enriched,
            "custom_audience_entries_before": before_rows,
            "custom_audience_entries_after": after_rows,
        }
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"Backup JSON: {backup_path}")
        print("")

        # Validazione
        if need_resolve:
            failed = []
            for r in need_resolve:
                aft = after_by_key.get(key(r), {})
                if not (aft.get("name") or "").strip():
                    failed.append(r["id"])
            if failed:
                print(
                    "VALIDAZIONE FALLITA: dopo enrich restano senza name (permessi token, "
                    f"audience non accessibile, o errore API): {failed}",
                    file=sys.stderr,
                )
                return 3
            print(
                f"VALIDAZIONE OK: {len(need_resolve)} voce/i senza name in risposta ad set "
                f"ora hanno name da CustomAudience API."
            )
            return 0

        if had_names:
            # già tutti con name: coerenza dopo enrich
            mismatches = []
            for r in had_names:
                aft = after_by_key.get(key(r), {})
                if (aft.get("name") or "").strip() != r["name"]:
                    mismatches.append(r["id"])
            if mismatches:
                print(
                    f"VALIDAZIONE FALLITA: name cambiati dopo enrich (ines atteso): {mismatches}",
                    file=sys.stderr,
                )
                return 3
            print(
                "VALIDAZIONE OK: Meta aveva già i name nel targeting; enrich non li ha alterati."
            )
            return 0

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
