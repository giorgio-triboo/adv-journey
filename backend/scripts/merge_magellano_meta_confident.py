#!/usr/bin/env python3
"""
Merge Magellano <-> Meta con punteggio di confidenza.
Assegna meta_campaign_id, meta_adset_id, meta_ad_id SOLO quando la probabilità di match è >= 99%.

Match:
- 1. facebook_id (Magellano) = meta_lead_id (Meta): identificatore univoco, match certo
- 2. In alternativa: email + telefono + data (base 75% + bonus)
- Telefono match (normalizzato): +15%
- Data entro 24h: +12%
- Data entro 7 giorni: +8%
- Penalità ambiguità: -15% per ogni altro candidato Meta con stessa email

Uso:
    python scripts/merge_magellano_meta_confident.py [--output file.csv] [--min-confidence 99]
"""
import os
import sys
import re
import argparse
from datetime import datetime
from collections import defaultdict

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")
MAGELLANO_CSV = os.path.join(EXPORTS_DIR, "magellano-export", "magellano_export_unificato.csv")
META_CSV = os.path.join(EXPORTS_DIR, "meta-export", "meta_export_unificato.csv")

DEFAULT_ACCOUNT_PRIORITY = ["2036679963222241", "990978329857711", "1209978493874443"]


def _norm_email(val) -> str | None:
    if pd.isna(val):
        return None
    s = str(val).strip().lower()
    return s if s and s != "nan" else None


def _norm_phone(val) -> str | None:
    if pd.isna(val):
        return None
    s = re.sub(r"\D", "", str(val).strip())
    return s[-9:] if len(s) >= 9 else (s if s else None)


def _norm_fb_id(val) -> str | None:
    if pd.isna(val):
        return None
    s = str(val).strip().upper()
    if s.startswith("I:"):
        s = s[2:].strip()
    try:
        return str(int(float(s)))
    except (ValueError, TypeError):
        return s if s and s != "NAN" else None


def _to_int_str(s) -> str | None:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    ss = str(s).strip()
    if not ss or ss.lower() == "nan":
        return None
    if ss.replace(".0", "").replace(".", "").isdigit():
        return ss.replace(".0", "").split(".")[0]
    return ss


def _parse_date_mag(val) -> datetime | None:
    if pd.isna(val):
        return None
    s = str(val).strip()[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt)
        except ValueError:
            continue
    return None


def _parse_date_meta(val) -> datetime | None:
    if pd.isna(val):
        return None
    s = str(val).strip()[:25]
    for fmt, size in [("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)]:
        try:
            return datetime.strptime(s[:size], fmt)
        except ValueError:
            continue
    return None


def compute_confidence(mag_row, meta_row, n_candidates: int) -> float:
    mag_fb = _norm_fb_id(mag_row.get("Facebook Id") or mag_row.get("facebook_id"))
    meta_lead = _norm_fb_id(meta_row.get("meta_lead_id"))
    if mag_fb and meta_lead and mag_fb == meta_lead:
        return 100.0  # match certo (stesso ID) — passa soglia 99%

    mag_em = _norm_email(mag_row.get("Email"))
    meta_em = _norm_email(meta_row.get("email"))
    if not mag_em or not meta_em or mag_em != meta_em:
        return 0.0
    score = 75.0

    mag_ph = _norm_phone(mag_row.get("Telephone"))
    meta_ph = _norm_phone(meta_row.get("phone"))
    if mag_ph and meta_ph and mag_ph == meta_ph:
        score += 15.0

    mag_dt = _parse_date_mag(mag_row.get("Subscr. date"))
    meta_dt = _parse_date_meta(meta_row.get("created_time"))
    if mag_dt and meta_dt:
        delta = abs((mag_dt - meta_dt).total_seconds())
        if delta <= 86400:
            score += 12.0
        elif delta <= 7 * 86400:
            score += 8.0

    score -= (n_candidates - 1) * 15
    return max(0.0, min(100.0, score))


def merge_with_confidence(
    magellano_path: str = None,
    meta_path: str = None,
    output_path: str = None,
    min_confidence: float = 99.0,
    account_priority: list = None,
) -> dict:
    magellano_path = magellano_path or MAGELLANO_CSV
    meta_path = meta_path or META_CSV
    output_path = output_path or magellano_path
    account_priority = account_priority or DEFAULT_ACCOUNT_PRIORITY

    if not os.path.isfile(magellano_path):
        raise FileNotFoundError(f"File non trovato: {magellano_path}")
    if not os.path.isfile(meta_path):
        raise FileNotFoundError(f"File non trovato: {meta_path}")

    mag = pd.read_csv(magellano_path)
    meta = pd.read_csv(
        meta_path,
        sep=";",
        dtype={"campaign_id": str, "adset_id": str, "ad_id": str},
        keep_default_na=True,
    )

    meta["_created"] = meta["created_time"].apply(_parse_date_meta)
    meta["_fb_id"] = meta["meta_lead_id"].apply(_norm_fb_id)
    meta_by_email = defaultdict(list)
    meta_by_fb_id = defaultdict(list)
    for i, row in meta.iterrows():
        em = _norm_email(row.get("email"))
        fb = row.get("_fb_id")
        if em:
            meta_by_email[em].append(row)
        if fb:
            meta_by_fb_id[fb].append(row)
    # Ordina candidati per data (prima entrata per prima), poi account_priority per parità
    def _sort_key(row):
        created = row.get("_created") or datetime.max
        src = str(row.get("_source_file", ""))
        prio = next((i for i, acc in enumerate(account_priority) if acc in src), 999)
        return (created, prio)

    for em in meta_by_email:
        meta_by_email[em].sort(key=_sort_key)
    for fb in meta_by_fb_id:
        meta_by_fb_id[fb].sort(key=_sort_key)

    for c in ("meta_campaign_id", "meta_adset_id", "meta_ad_id"):
        if c in mag.columns:
            mag = mag.drop(columns=[c])

    stats = {"total_mag": len(mag), "matched": 0, "below_threshold": 0, "no_candidate": 0, "id_match": 0, "email_match": 0}
    meta_campaign_id = []
    meta_adset_id = []
    meta_ad_id = []

    for _, mrow in mag.iterrows():
        mag_fb = _norm_fb_id(mrow.get("Facebook Id") or mrow.get("facebook_id"))
        em = _norm_email(mrow.get("Email"))
        # 1. Match per facebook_id (identificatore univoco in Meta e Magellano)
        candidates = meta_by_fb_id.get(mag_fb) if mag_fb else None
        # 2. In alternativa: email + telefono + data
        if not candidates and em and em in meta_by_email:
            candidates = meta_by_email[em]
        if not candidates:
            meta_campaign_id.append(None)
            meta_adset_id.append(None)
            meta_ad_id.append(None)
            stats["no_candidate"] += 1
            continue

        n = len(candidates)
        best_row = None

        # Usa la PRIMA entrata che passa la soglia (evita match con seconda presentazione)
        for meta_row in candidates:
            conf = compute_confidence(mrow, meta_row, n)
            if conf >= min_confidence:
                best_row = meta_row
                break  # primo per data che passa: stop, no match fittizi con entrate successive

        if best_row is not None:
            meta_campaign_id.append(_to_int_str(best_row.get("campaign_id")))
            meta_adset_id.append(_to_int_str(best_row.get("adset_id")))
            meta_ad_id.append(_to_int_str(best_row.get("ad_id")))
            stats["matched"] += 1
            if _norm_fb_id(mrow.get("Facebook Id") or mrow.get("facebook_id")) == _norm_fb_id(best_row.get("meta_lead_id")):
                stats["id_match"] += 1
            else:
                stats["email_match"] += 1
        else:
            meta_campaign_id.append(None)
            meta_adset_id.append(None)
            meta_ad_id.append(None)
            stats["below_threshold"] += 1

    mag["meta_campaign_id"] = meta_campaign_id
    mag["meta_adset_id"] = meta_adset_id
    mag["meta_ad_id"] = meta_ad_id
    mag.to_csv(output_path, index=False, encoding="utf-8")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Merge Magellano-Meta con confidenza >= 99%")
    parser.add_argument("--output", "-o", type=str, default=None)
    parser.add_argument("--magellano", type=str, default=None)
    parser.add_argument("--meta", type=str, default=None)
    parser.add_argument("--min-confidence", type=float, default=99.0)
    parser.add_argument("--account-priority", type=str, default=None)
    args = parser.parse_args()

    account_priority = None
    if args.account_priority:
        account_priority = [a.strip() for a in args.account_priority.split(",") if a.strip()]

    try:
        stats = merge_with_confidence(
            magellano_path=args.magellano,
            meta_path=args.meta,
            output_path=args.output,
            min_confidence=args.min_confidence,
            account_priority=account_priority,
        )
        print(f"Aggiornato: {args.output or MAGELLANO_CSV}")
        print(f"Totale Magellano: {stats['total_mag']}")
        print(f"Match con confidenza >= {args.min_confidence}%: {stats['matched']}")
        print(f"  - per meta_lead_id = facebook_id: {stats['id_match']}")
        print(f"  - per email + altri segnali: {stats['email_match']}")
        print(f"Sotto soglia: {stats['below_threshold']}")
        print(f"Nessun candidato Meta: {stats['no_candidate']}")
    except Exception as e:
        print(f"Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
