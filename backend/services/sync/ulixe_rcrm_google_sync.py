"""
Sync RCRM Ulixe in ulixe_rcrm_temp da Google Sheet o (fallback) file locali.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy.orm import Session

from models import UlixeRcrmTemp
from scripts.load_ulixe_rcrm_temp import (
    EXPORTS_DIR,
    load_csv,
    load_rcrm_dict_rows,
    parse_period_from_filename,
)
from services.integrations.google_sheets_rcrm import (
    effective_sheet_name_template,
    fetch_ulixe_rcrm_sheet_values,
    is_rcrm_google_sheet_configured,
    sheet_title_for_period,
    sheet_values_to_rcrm_rows,
)

logger = logging.getLogger("services.sync.ulixe_rcrm_google_sync")


def _sync_from_google(db: Session, period: str) -> dict[str, Any]:
    raw = fetch_ulixe_rcrm_sheet_values(period)
    rows = sheet_values_to_rcrm_rows(raw)
    if not rows:
        raise ValueError("Foglio Google vuoto o senza righe dati dopo l'intestazione.")

    deleted = (
        db.query(UlixeRcrmTemp)
        .filter(UlixeRcrmTemp.period == period)
        .delete(synchronize_session=False)
    )

    source_label = "google_sheet"
    loaded = load_rcrm_dict_rows(rows, period, db, source_label)

    _tpl = effective_sheet_name_template()
    sheet_tab = sheet_title_for_period(period, _tpl) if _tpl else None
    return {
        "mode": "google_sheet",
        "period": period,
        "sheet_tab": sheet_tab,
        "deleted_before": int(deleted),
        "rows_loaded": int(loaded),
        "sheet_rows_raw": len(raw) - 1 if raw else 0,
    }


def _sync_from_local_files(db: Session, period: str | None) -> dict[str, Any]:
    try:
        os.makedirs(EXPORTS_DIR, exist_ok=True)
    except OSError as e:
        raise FileNotFoundError(f"Impossibile creare la directory export: {EXPORTS_DIR} ({e})") from e

    files = [
        f
        for f in os.listdir(EXPORTS_DIR)
        if f.lower().startswith("rcrm-") and f.lower().endswith(".csv")
    ]
    files.sort()
    if not files:
        raise FileNotFoundError("Nessun file rcrm-*.csv trovato per la sync")

    stats: dict[str, Any] = {
        "mode": "local_files",
        "total_files": len(files),
        "per_period": {},
        "total_deleted": 0,
        "total_loaded": 0,
        "skipped_files": [],
    }

    for filename in files:
        p = parse_period_from_filename(filename)
        if not p:
            stats["skipped_files"].append({"file": filename, "reason": "Periodo non riconosciuto"})
            continue
        if period and p != period:
            continue
        path = os.path.join(EXPORTS_DIR, filename)
        deleted_rows = (
            db.query(UlixeRcrmTemp).filter(UlixeRcrmTemp.period == p).delete(synchronize_session=False)
        )
        loaded_rows = load_csv(path, p, db)
        stats["per_period"].setdefault(p, {"deleted_before": 0, "rows_loaded": 0, "files": []})
        stats["per_period"][p]["deleted_before"] += int(deleted_rows)
        stats["per_period"][p]["rows_loaded"] += int(loaded_rows)
        stats["per_period"][p]["files"].append(filename)
        stats["total_deleted"] += int(deleted_rows)
        stats["total_loaded"] += int(loaded_rows)

    if period and period not in stats["per_period"]:
        raise FileNotFoundError(f"Nessun file rcrm-*.csv trovato per il periodo {period}")

    return stats


def run_ulixe_rcrm_sync(
    db: Session,
    period: str,
    *,
    source: str = "auto",
) -> dict[str, Any]:
    """
    source:
      - auto: Google Sheet se configurato, altrimenti file in exports/ulixe_temp
      - google_sheet: solo API Google
      - local_files: solo file rcrm-*.csv
    """
    src = (source or "auto").strip().lower()
    if src not in ("auto", "google_sheet", "local_files"):
        raise ValueError('source deve essere "auto", "google_sheet" o "local_files"')

    if src == "google_sheet" or (src == "auto" and is_rcrm_google_sheet_configured()):
        if not is_rcrm_google_sheet_configured():
            raise RuntimeError(
                "Google Sheet RCRM non configurato: imposta in .env le variabili "
                "ULIXE_RCRM_GOOGLE_SA_* (service account) e ULIXE_RCRM_GOOGLE_SPREADSHEET_ID; "
                "condividi il foglio con ULIXE_RCRM_GOOGLE_SA_CLIENT_EMAIL."
            )
        return _sync_from_google(db, period)

    if src == "local_files" or src == "auto":
        return _sync_from_local_files(db, period)

    raise RuntimeError("Impossibile eseguire la sync RCRM (nessuna sorgente disponibile).")
