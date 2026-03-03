#!/usr/bin/env python3
"""
Estrae tutti i file XLS/XLSX da backend/exports/magellano-export e li unisce in un unico CSV.

Regole:
- Solo Id source = 1 (FBLeadAds); le altre fonti non vengono usate
- Un utente può essere in più campagne (188, 190, 199)
- Un utente può apparire una sola volta per campagna: dedup (Id user, Id campaign), prima data

Uso:
    python scripts/merge_magellano_export.py [--output file.csv]
"""
import os
import sys
import argparse
from datetime import datetime

import pandas as pd

# Path relativo allo script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
EXPORT_DIR = os.path.join(PROJECT_ROOT, "exports", "magellano-export")


def merge_magellano_export(
    export_dir: str = None,
    output_path: str = None,
    add_source_column: bool = True,
) -> str:
    """Legge tutti i file XLS/XLSX dalla cartella export e li unisce in un CSV."""
    dir_path = export_dir or EXPORT_DIR
    if not os.path.isdir(dir_path):
        raise FileNotFoundError(f"Cartella non trovata: {dir_path}")

    xls_files = []
    for f in sorted(os.listdir(dir_path)):
        if f.endswith(".xls") or f.endswith(".xlsx"):
            xls_files.append(os.path.join(dir_path, f))

    if not xls_files:
        raise FileNotFoundError(f"Nessun file .xls/.xlsx trovato in {dir_path}")

    dfs = []
    for path in xls_files:
        df = pd.read_excel(path)
        if add_source_column:
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

    # Un utente una sola volta per campagna: dedup (Id user, Id campaign), prima data
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

    id_user_col = next((c for c in combined.columns if "id user" in str(c).lower()), None)
    id_campaign_col = next((c for c in combined.columns if "id campaign" in str(c).lower()), None)
    if id_user_col and id_user_col in combined.columns:
        combined["_subscr"] = combined["Subscr. date"].apply(_parse_subscr)
        combined = combined.sort_values("_subscr", ascending=True)
        before = len(combined)
        subset = [id_user_col]
        if id_campaign_col and id_campaign_col in combined.columns:
            subset.append(id_campaign_col)
        combined = combined.drop_duplicates(subset=subset, keep="first")
        combined = combined.drop(columns=["_subscr"], errors="ignore")
        dropped = before - len(combined)
        if dropped:
            print(f"Deduplicati {dropped} record (stesso user+campagna, tenuta prima data)")

    if output_path is None:
        output_path = os.path.join(dir_path, "magellano_export_unificato.csv")

    combined.to_csv(output_path, index=False, encoding="utf-8-sig")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Unisce tutti i file Magellano export in un unico CSV")
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="Cartella di input con i file XLS/XLSX (default: exports/magellano-export)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Path del file CSV di output (default: magellano_export_unificato.csv nella cartella input)",
    )
    parser.add_argument(
        "--no-source",
        action="store_true",
        help="Non aggiungere la colonna _source_file con il nome del file origine",
    )
    args = parser.parse_args()

    try:
        out = merge_magellano_export(
            export_dir=args.input,
            output_path=args.output,
            add_source_column=not args.no_source,
        )
        print(f"Creato: {out}")
    except Exception as e:
        print(f"Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
