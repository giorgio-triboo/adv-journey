#!/usr/bin/env python3
"""
Unisce tutti i file CSV da backend/exports/meta-export in un unico CSV.

Uso:
    python scripts/merge_meta_export.py [--output file.csv]
"""
import os
import sys
import argparse
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
EXPORT_DIR = os.path.join(PROJECT_ROOT, "exports", "meta-export")


def merge_meta_export(
    input_dir: str = None,
    output_path: str = None,
    add_source_column: bool = True,
    account_priority: list[str] = None,
) -> str:
    """
    Legge tutti i file CSV dalla cartella export e li unisce in un CSV.

    input_dir: cartella sorgente (default: exports/meta-export)
    account_priority: lista di account_id (es. ['2036679963222241', '990978329857711']).
        I file che contengono questi account vengono messi per primi nell'ordine specificato.
        Utile per il merge con Magellano: drop_duplicates(keep='first') terrà le righe
        dall'account preferito quando la stessa email appare in più account.
    """
    export_dir = input_dir or EXPORT_DIR
    if not os.path.isdir(export_dir):
        raise FileNotFoundError(f"Cartella non trovata: {export_dir}")

    all_files = [
        os.path.join(export_dir, f)
        for f in os.listdir(export_dir)
        if f.endswith(".csv") and not f.startswith("meta_export_unificato")
    ]
    if not all_files:
        raise FileNotFoundError(f"Nessun file .csv trovato in {export_dir}")

    # Ordina: prima i file degli account in account_priority, poi gli altri
    def sort_key(path):
        name = os.path.basename(path)
        for i, acc_id in enumerate(account_priority or []):
            if acc_id in name:
                return (i, name)
        return (999, name)

    csv_files = sorted(all_files, key=sort_key)

    dfs = []
    for path in csv_files:
        df = pd.read_csv(path, sep=";", encoding="utf-8")
        if add_source_column:
            df["_source_file"] = os.path.basename(path)
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)

    if output_path is None:
        output_path = os.path.join(export_dir, "meta_export_unificato.csv")

    combined.to_csv(output_path, index=False, sep=";", encoding="utf-8-sig")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Unisce tutti i file Meta export in un unico CSV. "
        "Es: python scripts/merge_meta_export.py --dir exports/meta-export-0226"
    )
    parser.add_argument(
        "--dir", "-d",
        type=str,
        default=None,
        dest="input_dir",
        help="Cartella sorgente (default: exports/meta-export). "
             "Es: meta-export-0126, meta-export-0226",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Path del file CSV di output",
    )
    parser.add_argument(
        "--no-source",
        action="store_true",
        help="Non aggiungere la colonna _source_file",
    )
    parser.add_argument(
        "--account-priority",
        type=str,
        default=None,
        help="Account IDs da dare priorità (virgola-separati). Es: 2036679963222241,990978329857711. "
             "Quando la stessa email appare in più account, si terrà quella dell'account elencato per primo.",
    )
    args = parser.parse_args()

    account_priority = None
    if args.account_priority:
        account_priority = [a.strip() for a in args.account_priority.split(",") if a.strip()]

    # Resolve input_dir: se relativo, è rispetto a PROJECT_ROOT/exports
    input_dir = args.input_dir
    if input_dir and not os.path.isabs(input_dir):
        input_dir = os.path.join(PROJECT_ROOT, "exports", input_dir.lstrip("./"))

    try:
        out = merge_meta_export(
            input_dir=input_dir,
            output_path=args.output,
            add_source_column=not args.no_source,
            account_priority=account_priority,
        )
        print(f"Creato: {out}")
    except Exception as e:
        print(f"Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
