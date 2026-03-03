#!/usr/bin/env python3
"""
Validazione merge: confronta merge VECCHIO (email only) vs merge CONFIDENT (>=87%)
per le lead nel periodo indicato. Output CSV per controllo manuale.

Uso:
    python scripts/validate_merge_0101.py [--from-date 2026-01-01] [--to-date 2026-01-10] [--output report.csv]
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

def _parse_date_mag_safe(val):
    if pd.isna(val):
        return None
    s = str(val).strip()[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt)
        except ValueError:
            continue
    return None


def _norm_email(val):
    if pd.isna(val):
        return None
    s = str(val).strip().lower()
    return s if s and s != "nan" else None


def _norm_fb_id(val):
    if pd.isna(val):
        return None
    s = str(val).strip().upper()
    if s.startswith("I:"):
        s = s[2:].strip()
    try:
        return str(int(float(s)))
    except (ValueError, TypeError):
        return s if s and s != "NAN" else None


def _to_int_str(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    ss = str(s).strip()
    if not ss or ss.lower() == "nan":
        return None
    if ss.replace(".0", "").replace(".", "").isdigit():
        return ss.replace(".0", "").split(".")[0]
    return ss


def _parse_date_meta(val):
    if pd.isna(val):
        return None
    s = str(val).strip()[:25]
    for fmt, size in [("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)]:
        try:
            return datetime.strptime(s[:size], fmt)
        except ValueError:
            continue
    return None


# Import da merge confident (eseguire da backend dir: python scripts/validate_merge_0101.py)
sys.path.insert(0, PROJECT_ROOT)
from scripts.merge_magellano_meta_confident import compute_confidence, DEFAULT_ACCOUNT_PRIORITY


def run_validation(
    from_date: str = "2026-01-01",
    to_date: str = "2026-01-01",
    output_path: str = None,
):
    from_dt = datetime.strptime(from_date, "%Y-%m-%d").date()
    to_dt = datetime.strptime(to_date, "%Y-%m-%d").date()
    if from_dt > to_dt:
        from_dt, to_dt = to_dt, from_dt

    default_name = f"validate_merge_{from_date}_{to_date}.csv".replace("-", "")
    output_path = output_path or os.path.join(EXPORTS_DIR, "magellano-export", default_name)

    mag = pd.read_csv(MAGELLANO_CSV)
    meta = pd.read_csv(
        META_CSV,
        sep=";",
        dtype={"campaign_id": str, "adset_id": str, "ad_id": str},
        keep_default_na=True,
    )

    # Filtra per intervallo date
    mag["_subscr_date"] = mag["Subscr. date"].apply(_parse_date_mag_safe)
    mag_period = mag[
        mag["_subscr_date"].apply(lambda d: d and from_dt <= d.date() <= to_dt)
    ].copy()
    mag_period = mag_period.drop(columns=["_subscr_date"], errors="ignore")

    meta["_created_date"] = meta["created_time"].apply(_parse_date_meta)
    meta_period = meta[
        meta["_created_date"].apply(lambda d: d and from_dt <= d.date() <= to_dt)
    ].copy()
    # Ordina per prima entrata: usare sempre il record Meta con data più antica
    meta_period = meta_period.sort_values("_created_date", ascending=True)

    print(f"Magellano {from_date} → {to_date}: {len(mag_period)} righe")
    print(f"Meta {from_date} → {to_date}: {len(meta_period)} righe")

    # --- MERGE VECCHIO (email only, prima entrata per data) ---
    meta_by_em = {}
    for _, row in meta_period.iterrows():
        em = _norm_email(row.get("email"))
        if em and em not in meta_by_em:
            meta_by_em[em] = row

    old_campaign = []
    old_adset = []
    old_ad = []
    for _, mrow in mag_period.iterrows():
        em = _norm_email(mrow.get("Email"))
        r = meta_by_em.get(em)
        if r is not None:
            old_campaign.append(_to_int_str(r.get("campaign_id")))
            old_adset.append(_to_int_str(r.get("adset_id")))
            old_ad.append(_to_int_str(r.get("ad_id")))
        else:
            old_campaign.append(None)
            old_adset.append(None)
            old_ad.append(None)

    mag_period["old_meta_campaign_id"] = old_campaign
    mag_period["old_meta_adset_id"] = old_adset
    mag_period["old_meta_ad_id"] = old_ad

    # --- MERGE CONFIDENT (prima entrata per data) ---
    meta_by_email = defaultdict(list)
    for _, row in meta_period.iterrows():
        em = _norm_email(row.get("email"))
        if em:
            meta_by_email[em].append(row)
    for em in meta_by_email:
        meta_by_email[em].sort(key=lambda r: r.get("_created_date") or datetime.max)

    new_campaign = []
    new_adset = []
    new_ad = []
    match_type = []

    for idx, (_, mrow) in enumerate(mag_period.iterrows()):
        em = _norm_email(mrow.get("Email"))
        oc = old_campaign[idx] if idx < len(old_campaign) else None

        if not em or em not in meta_by_email:
            new_campaign.append(None)
            new_adset.append(None)
            new_ad.append(None)
            match_type.append("no_candidate")
            continue

        candidates = meta_by_email[em]
        n = len(candidates)
        best_score = 0.0
        best_row = None
        best_prio = 999

        for meta_row in candidates:
            conf = compute_confidence(mrow, meta_row, n)
            src = str(meta_row.get("_source_file", ""))
            prio = next((i for i, acc in enumerate(DEFAULT_ACCOUNT_PRIORITY) if acc in src), 999)
            if conf >= 87.0 and (conf > best_score or (conf == best_score and prio < best_prio)):
                best_score = conf
                best_row = meta_row
                best_prio = prio

        if best_row is not None:
            nc = _to_int_str(best_row.get("campaign_id"))
            na = _to_int_str(best_row.get("adset_id"))
            nad = _to_int_str(best_row.get("ad_id"))
            new_campaign.append(nc)
            new_adset.append(na)
            new_ad.append(nad)
            if oc is None and nc:
                match_type.append("new_only")
            elif oc and nc is None:
                match_type.append("old_only")
            elif str(oc or "") != str(nc or ""):
                match_type.append("DIFFERENT")
            else:
                match_type.append("same")
        else:
            new_campaign.append(None)
            new_adset.append(None)
            new_ad.append(None)
            match_type.append("below_threshold")

    mag_period["new_meta_campaign_id"] = new_campaign
    mag_period["new_meta_adset_id"] = new_adset
    mag_period["new_meta_ad_id"] = new_ad
    mag_period["match_type"] = match_type

    # Fix match_type: same vs DIFFERENT
    for i in range(len(mag_period)):
        oc = mag_period.iloc[i]["old_meta_campaign_id"]
        nc = mag_period.iloc[i]["new_meta_campaign_id"]
        mt = mag_period.iloc[i]["match_type"]
        if mt == "new_only" or mt == "old_only" or mt == "no_candidate" or mt == "below_threshold":
            continue
        if oc == nc or (pd.isna(oc) and pd.isna(nc)):
            mag_period.iloc[i, mag_period.columns.get_loc("match_type")] = "same"
        else:
            mag_period.iloc[i, mag_period.columns.get_loc("match_type")] = "DIFFERENT"

    mag_period.to_csv(output_path, index=False, encoding="utf-8")

    # Report
    same = (mag_period["match_type"] == "same").sum()
    diff = (mag_period["match_type"] == "DIFFERENT").sum()
    old_only = (mag_period["match_type"] == "old_only").sum()
    new_only = (mag_period["match_type"] == "new_only").sum()
    no_cand = (mag_period["match_type"] == "no_candidate").sum()
    below = (mag_period["match_type"] == "below_threshold").sum()

    print()
    print(f"=== REPORT {from_date} → {to_date} ===")
    print(f"Stesso risultato (vecchio = nuovo): {same}")
    print(f"DIFFERENTI (vecchio != nuovo):     {diff}")
    print(f"Solo vecchio aveva match:          {old_only} (confident li ha esclusi <87%)")
    print(f"Solo confident ha match:           {new_only}")
    print(f"Nessun candidato Meta:             {no_cand}")
    print(f"Sotto soglia 87%:                  {below}")
    print()
    print(f"Output: {output_path}")
    if diff > 0 or old_only > 0:
        print()
        print("⚠️  Controllare le righe con DIFFERENT e old_only nel CSV.")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Valida merge Magellano-Meta per periodo")
    parser.add_argument("--from-date", type=str, default="2026-01-01")
    parser.add_argument("--to-date", type=str, default="2026-01-01")
    parser.add_argument("--output", "-o", type=str, default=None)
    args = parser.parse_args()
    try:
        run_validation(args.from_date, args.to_date, args.output)
    except Exception as e:
        print(f"Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
