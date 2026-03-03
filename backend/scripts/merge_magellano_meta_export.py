#!/usr/bin/env python3
"""
Arricchisce magellano_export_unificato.csv con le colonne Meta (campaign_id, adset_id, ad_id).

Aggiunge al CSV Magellano le colonne: meta_campaign_id, meta_adset_id, meta_ad_id
dove c'è match su email (Magellano Email = Meta email).

La struttura del file resta quella Magellano (brand, msg_id, form_id, source, campaign_name,
magellano_campaign_id, Sent status, etc.) + gli ID Meta per correlazione con il DB.

Uso:
    python scripts/merge_magellano_meta_export.py [--output file.csv]
"""
import os
import sys
import argparse
from datetime import datetime

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")
MAGELLANO_CSV = os.path.join(EXPORTS_DIR, "magellano-export", "magellano_export_unificato.csv")
META_CSV = os.path.join(EXPORTS_DIR, "meta-export", "meta_export_unificato.csv")


def _norm_email(val) -> str | None:
    """Normalizza email per match: lowercase, strip."""
    if pd.isna(val):
        return None
    s = str(val).strip().lower()
    return s if s and s != "nan" else None


def _parse_date_meta(val):
    """Parse created_time Meta per ordinamento."""
    if pd.isna(val):
        return datetime.max  # senza data va in fondo
    s = str(val).strip()[:25]
    for fmt, size in [("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)]:
        try:
            return datetime.strptime(s[:size], fmt)
        except ValueError:
            continue
    return datetime.max


def _to_int_str(s) -> str | None:
    """Converti a stringa senza perdita precisione (ID Meta > 2^53)."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    ss = str(s).strip()
    if not ss or ss.lower() == "nan":
        return None
    # Evita float(): per numeri > 2^53 perde precisione (067→064)
    if ss.replace(".0", "").replace(".", "").isdigit() or ss.lstrip("-").replace(".", "").isdigit():
        return ss.replace(".0", "").split(".")[0]
    return ss


def merge_exports(
    magellano_path: str = None,
    meta_path: str = None,
    output_path: str = None,
) -> str:
    """
    Arricchisce il CSV Magellano con meta_campaign_id, meta_adset_id, meta_ad_id.
    Sovrascrive il file Magellano o scrive su output_path.
    """
    magellano_path = magellano_path or MAGELLANO_CSV
    meta_path = meta_path or META_CSV
    output_path = output_path or magellano_path

    if not os.path.isfile(magellano_path):
        raise FileNotFoundError(f"File non trovato: {magellano_path}")
    if not os.path.isfile(meta_path):
        raise FileNotFoundError(f"File non trovato: {meta_path}")

    mag = pd.read_csv(magellano_path)
    # dtype=str per campaign_id, adset_id, ad_id: evitare perdita precisione (ID > 2^53 → 067 diventa 064)
    meta = pd.read_csv(
        meta_path,
        sep=";",
        dtype={"campaign_id": str, "adset_id": str, "ad_id": str},
        keep_default_na=True,
    )

    mag["_email_norm"] = mag["Email"].apply(_norm_email)
    meta["_email_norm"] = meta["email"].apply(_norm_email)
    meta["_created"] = meta["created_time"].apply(_parse_date_meta)

    # Usa sempre la PRIMA entrata della lead (per data): evita match fittizi
    # con la seconda volta che la mail si presenta in Meta
    meta_sorted = meta.sort_values("_created", ascending=True)
    meta_sub = meta_sorted[["_email_norm", "campaign_id", "adset_id", "ad_id"]].drop_duplicates(
        subset=["_email_norm"], keep="first"
    )
    merged = mag.merge(
        meta_sub,
        on="_email_norm",
        how="left",
        suffixes=("", "_meta"),
    )

    out = merged.drop(columns=["_email_norm", "campaign_id", "adset_id", "ad_id"], errors="ignore")
    out["meta_campaign_id"] = merged["campaign_id"].apply(_to_int_str)
    out["meta_adset_id"] = merged["adset_id"].apply(_to_int_str)
    out["meta_ad_id"] = merged["ad_id"].apply(_to_int_str)

    out.to_csv(output_path, index=False, encoding="utf-8")
    matched = out["meta_campaign_id"].notna().sum()
    print(f"Aggiornato: {output_path}")
    print(f"Righe: {len(out)}, Match con Meta: {int(matched)}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Arricchisce magellano_export_unificato con colonne Meta (campaign, adset, ad ID)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Path output (default: sovrascrive magellano_export_unificato.csv)",
    )
    parser.add_argument(
        "--magellano",
        type=str,
        default=None,
        help="Path CSV Magellano",
    )
    parser.add_argument(
        "--meta",
        type=str,
        default=None,
        help="Path CSV Meta",
    )
    args = parser.parse_args()

    try:
        merge_exports(
            magellano_path=args.magellano,
            meta_path=args.meta,
            output_path=args.output,
        )
    except Exception as e:
        print(f"Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
