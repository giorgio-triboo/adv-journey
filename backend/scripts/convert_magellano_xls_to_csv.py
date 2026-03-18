#!/usr/bin/env python3
"""
Converte i file Magellano (.xls/.xlsx) in CSV mantenendo i campi come testo.

Obiettivo: evitare che ID grandi (es. Facebook Id) escano in notazione scientifica
tipo `2.615922e+16` e perdere precisione.

Uso:
  docker compose exec backend python scripts/convert_magellano_xls_to_csv.py \
    --input-dir exports/magellano-export-0326 \
    --output-dir exports/magellano-export-0326/_converted_csv
"""

from __future__ import annotations

import os
import re
import sys
import argparse
from decimal import Decimal, InvalidOperation

import pandas as pd


def _expand_scientific_to_intlike(val: str) -> str:
    """
    Se il valore è in notazione scientifica (es. 2.6e+16), converte in stringa
    senza esponente (quando possibile).
    """
    s = str(val).strip()
    if not s:
        return s

    # Fast path: niente esponente
    if "e" not in s.lower():
        return s

    try:
        d = Decimal(s)
    except InvalidOperation:
        return s

    # Se è un intero "matematico", riportalo come intero
    if d == d.to_integral_value():
        return str(d.to_integral_value())

    # Altrimenti espandi in formato decimale senza esponente
    # (per ID dovrebbe non servire, ma è safe).
    return format(d, "f").rstrip("0").rstrip(".")


def _looks_like_id_column(col_name: str) -> bool:
    n = str(col_name).strip().lower()
    # Copri i nomi più comuni negli export Magellano
    return any(
        token in n
        for token in [
            "facebook id",
            "facebook_id",
            "id user",
            "id_campaign",
            "id campaign",
            "id source",
            "id aff",
            "idmessaggio",
            "id messaggio",
            "gruppocepu_idmessaggio",
        ]
    )


def convert_dir(input_dir: str, output_dir: str) -> list[str]:
    if not os.path.isdir(input_dir):
        raise FileNotFoundError(f"Input directory non trovata: {input_dir}")
    os.makedirs(output_dir, exist_ok=True)

    paths = [
        os.path.join(input_dir, f)
        for f in sorted(os.listdir(input_dir))
        if f.lower().endswith((".xls", ".xlsx"))
    ]
    if not paths:
        raise FileNotFoundError(f"Nessun file .xls/.xlsx trovato in {input_dir}")

    out_files: list[str] = []
    for path in paths:
        in_name = os.path.basename(path)
        out_name = os.path.splitext(in_name)[0] + ".csv"
        out_path = os.path.join(output_dir, out_name)

        # dtype=str evita parsing numerico -> riduce notazione scientifica
        df = pd.read_excel(path, dtype=str)

        # Applica una normalizzazione "anti-scientific" solo sulle colonne che sembrano ID.
        for col in df.columns:
            if _looks_like_id_column(str(col)):
                df[col] = df[col].apply(
                    lambda v: _expand_scientific_to_intlike(v) if isinstance(v, str) else v
                )

        # Aggiunge una colonna sorgente: utile per eventuali dedup/merge.
        df["_source_file"] = in_name

        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        out_files.append(out_path)

        print(f"Creato: {out_path} (cols={len(df.columns)}, righe={len(df)})")

    return out_files


def main() -> None:
    p = argparse.ArgumentParser(description="Converti Magellano export XLS in CSV (testuale)")
    p.add_argument("--input-dir", "-i", required=True, help="Cartella con .xls/.xlsx")
    p.add_argument("--output-dir", "-o", required=True, help="Cartella output CSV convertiti")
    args = p.parse_args()

    try:
        convert_dir(args.input_dir, args.output_dir)
    except Exception as e:
        print(f"Errore: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

