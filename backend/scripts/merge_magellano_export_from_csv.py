#!/usr/bin/env python3
"""
Esegue il merge dei file Magellano convertiti in CSV (da convert_magellano_xls_to_csv.py)
in un unico CSV "unificato".

Stesse regole dell'esistente merge_magellano_export.py:
  - Solo Id source = 1 (FBLeadAds)
  - Dedup: (Id user, Id campaign), prima data
  - Un utente può apparire in più campagne
"""

from __future__ import annotations

import os
import sys
import argparse
from datetime import datetime

import pandas as pd


def merge_from_csv(
    input_dir: str,
    output_path: str | None = None,
    add_source_column: bool = False,
) -> str:
    if not os.path.isdir(input_dir):
        raise FileNotFoundError(f"Cartella non trovata: {input_dir}")

    csv_files = [
        os.path.join(input_dir, f)
        for f in sorted(os.listdir(input_dir))
        if f.lower().endswith(".csv") and not f.startswith("magellano_export_unificato")
    ]
    if not csv_files:
        raise FileNotFoundError(f"Nessun file .csv trovato in {input_dir}")

    dfs: list[pd.DataFrame] = []
    for path in csv_files:
        # dtype=str per non reintrodurre notazione scientifica e perdere precisione
        df = pd.read_csv(path, dtype=str)
        if add_source_column and "_source_file" not in df.columns:
            df["_source_file"] = os.path.basename(path)
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)

    # Solo Id source = 1 (FBLeadAds)
    id_source_col = next((c for c in combined.columns if "id source" in str(c).lower()), None)
    if id_source_col and id_source_col in combined.columns:
        before_src = len(combined)
        combined = combined[pd.to_numeric(combined[id_source_col], errors="coerce") == 1]
        dropped_src = before_src - len(combined)
        if dropped_src:
            print(f"Esclusi {dropped_src} record (Id source != 1): {len(combined)} rimasti")

    def _parse_subscr(val):
        if pd.isna(val):
            return datetime.max
        s = str(val).strip()[:19]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt)
            except ValueError:
                continue
        return datetime.max

    # Dedup (Id user, Id campaign), prima data
    id_user_col = next((c for c in combined.columns if "id user" in str(c).lower()), None)
    id_campaign_col = next((c for c in combined.columns if "id campaign" in str(c).lower()), None)

    if id_user_col and id_user_col in combined.columns and "Subscr. date" in combined.columns:
        combined["_subscr"] = combined["Subscr. date"].apply(_parse_subscr)
        combined = combined.sort_values("_subscr", ascending=True)

        subset = [id_user_col]
        if id_campaign_col and id_campaign_col in combined.columns:
            subset.append(id_campaign_col)

        before = len(combined)
        combined = combined.drop_duplicates(subset=subset, keep="first")
        combined = combined.drop(columns=["_subscr"], errors="ignore")
        dropped = before - len(combined)
        if dropped:
            print(f"Deduplicati {dropped} record (stesso user+campagna, tenuta prima data)")

    if output_path is None:
        output_path = os.path.join(input_dir, "magellano_export_unificato.csv")

    combined.to_csv(output_path, index=False, encoding="utf-8-sig")
    return output_path


def main() -> None:
    p = argparse.ArgumentParser(description="Merge Magellano da CSV convertiti (testuale)")
    p.add_argument("--input-dir", "-i", required=True, help="Cartella CSV convertiti (output conversione)")
    p.add_argument(
        "--output",
        "-o",
        default=None,
        help="Path CSV unificato di output (default: nella cartella input)",
    )
    p.add_argument("--no-source-col", action="store_true", help="Non aggiungere _source_file (se mancante)")
    args = p.parse_args()

    try:
        out = merge_from_csv(
            input_dir=args.input_dir,
            output_path=args.output,
            add_source_column=not args.no_source_col,
        )
        print(f"Creato: {out}")
    except Exception as e:
        print(f"Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

