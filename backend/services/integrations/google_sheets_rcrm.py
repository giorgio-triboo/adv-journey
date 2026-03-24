"""
Lettura dati RCRM Ulixe da Google Sheets API (service account).
Credenziali solo da variabili d'ambiente (.env); condividere il foglio con client_email.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import settings

logger = logging.getLogger("services.integrations.google_sheets_rcrm")

SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)
MAX_RETRIES = 3
RETRY_DELAY_SEC = 2.0


def _normalize_private_key(raw: str) -> str:
    """Supporta PEM con newline reali o sequenza letterale \\n nel .env."""
    s = (raw or "").strip()
    if not s:
        return ""
    return s.replace("\\n", "\n")


def build_service_account_info() -> dict[str, str] | None:
    """
    Costruisce il dict atteso da Credentials.from_service_account_info.
    Ritorna None se manca un campo obbligatorio.
    """
    pk = _normalize_private_key(settings.ULIXE_RCRM_GOOGLE_SA_PRIVATE_KEY or "")
    project_id = (settings.ULIXE_RCRM_GOOGLE_SA_PROJECT_ID or "").strip()
    private_key_id = (settings.ULIXE_RCRM_GOOGLE_SA_PRIVATE_KEY_ID or "").strip()
    client_email = (settings.ULIXE_RCRM_GOOGLE_SA_CLIENT_EMAIL or "").strip()
    client_id = (settings.ULIXE_RCRM_GOOGLE_SA_CLIENT_ID or "").strip()
    client_x509 = (settings.ULIXE_RCRM_GOOGLE_SA_CLIENT_X509_CERT_URL or "").strip()

    if not all([pk, project_id, private_key_id, client_email, client_id, client_x509]):
        return None

    return {
        "type": (settings.ULIXE_RCRM_GOOGLE_SA_TYPE or "service_account").strip(),
        "project_id": project_id,
        "private_key_id": private_key_id,
        "private_key": pk,
        "client_email": client_email,
        "client_id": client_id,
        "auth_uri": (settings.ULIXE_RCRM_GOOGLE_SA_AUTH_URI or "").strip(),
        "token_uri": (settings.ULIXE_RCRM_GOOGLE_SA_TOKEN_URI or "").strip(),
        "auth_provider_x509_cert_url": (
            settings.ULIXE_RCRM_GOOGLE_SA_AUTH_PROVIDER_X509_CERT_URL or ""
        ).strip(),
        "client_x509_cert_url": client_x509,
    }


def is_rcrm_google_sheet_configured() -> bool:
    return bool(
        build_service_account_info()
        and (settings.ULIXE_RCRM_GOOGLE_SPREADSHEET_ID or "").strip()
    )


def _escape_sheet_title(title: str) -> str:
    return title.replace("'", "''")


def _build_sheets_service_from_info(info: dict[str, str]):
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def effective_sheet_name_template() -> str | None:
    """
    Template nome tab da usare, o None se si usa solo GID (legacy).
    """
    name_tpl = (settings.ULIXE_RCRM_GOOGLE_SHEET_NAME_TEMPLATE or "").strip()
    gid = settings.ULIXE_RCRM_GOOGLE_SHEET_GID
    if name_tpl:
        return name_tpl
    if gid is None:
        return "{mm}-ulixe-rcrm"
    return None


def sheet_title_for_period(period: str, template: str) -> str:
    """
    period: YYYY-MM. template: es. "{mm}-ulixe-rcrm" → 03-ulixe-rcrm per marzo.
    Supporta anche {yyyy} (anno a 4 cifre) e {year} come alias.
    """
    dt = datetime.strptime(f"{period.strip()}-01", "%Y-%m-%d")
    mm = f"{dt.month:02d}"
    yyyy = str(dt.year)
    return template.format(mm=mm, MM=mm, yyyy=yyyy, year=yyyy)


def _sheet_title_for_gid(service: Any, spreadsheet_id: str, sheet_gid: int) -> str | None:
    try:
        meta = (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))")
            .execute()
        )
    except HttpError as e:
        logger.error("Errore metadata spreadsheet %s: %s", spreadsheet_id, e, exc_info=True)
        raise
    for sheet in meta.get("sheets", []):
        props = sheet.get("properties") or {}
        if props.get("sheetId") == sheet_gid:
            return props.get("title")
    return None


def _fetch_values_with_retry(service: Any, spreadsheet_id: str, range_a1: str) -> list[list[Any]]:
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            result = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=range_a1)
                .execute()
            )
            return result.get("values") or []
        except HttpError as e:
            last_err = e
            status = e.resp.status if e.resp is not None else None
            if status == 429 and attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_SEC * (attempt + 1))
                continue
            raise
    if last_err:
        raise last_err
    return []


def _normalize_header(cell: str) -> str:
    return re.sub(r"\s+", "", (cell or "").strip().lower())


def sheet_values_to_rcrm_rows(values: list[list[Any]]) -> list[dict[str, str]]:
    """
    Converte righe grezze API in dict con chiavi IDMessaggio e RCRM (stringhe).
    Campi mancanti come stringa vuota.
    """
    if not values:
        return []
    header_row = [str(c or "").strip() for c in values[0]]
    norm = [_normalize_header(h) for h in header_row]

    id_idx = None
    rcrm_idx = None
    for i, hn in enumerate(norm):
        if hn in ("idmessaggio", "id_messaggio"):
            id_idx = i
        if hn == "rcrm":
            rcrm_idx = i

    if id_idx is None or rcrm_idx is None:
        raise ValueError(
            "Intestazioni foglio non valide: servono colonne IDMessaggio e RCRM "
            f"(trovate: {header_row})"
        )

    rows: list[dict[str, str]] = []
    for raw in values[1:]:
        if not raw:
            continue

        def cell(j: int) -> str:
            if j >= len(raw):
                return ""
            v = raw[j]
            if v is None:
                return ""
            return str(v).strip()

        msg_id = cell(id_idx)
        rcrm = cell(rcrm_idx)
        if not msg_id:
            continue
        rows.append({"IDMessaggio": msg_id, "RCRM": rcrm})
    return rows


def fetch_ulixe_rcrm_sheet_values(period: str) -> list[list[Any]]:
    """
    Scarica i valori dal range configurato.

    - Con ULIXE_RCRM_GOOGLE_SHEET_NAME_TEMPLATE (default {mm}-ulixe-rcrm): tab dal periodo YYYY-MM.
    - Altrimenti, se impostato ULIXE_RCRM_GOOGLE_SHEET_GID: tab risolto via GID (legacy).
    """
    info = build_service_account_info()
    if not info:
        raise RuntimeError(
            "Credenziali Google Sheets (service account) incomplete: imposta in .env "
            "ULIXE_RCRM_GOOGLE_SA_PROJECT_ID, ULIXE_RCRM_GOOGLE_SA_PRIVATE_KEY_ID, "
            "ULIXE_RCRM_GOOGLE_SA_PRIVATE_KEY, ULIXE_RCRM_GOOGLE_SA_CLIENT_EMAIL, "
            "ULIXE_RCRM_GOOGLE_SA_CLIENT_ID, ULIXE_RCRM_GOOGLE_SA_CLIENT_X509_CERT_URL "
            "(valori dal JSON del service account)."
        )
    sid = (settings.ULIXE_RCRM_GOOGLE_SPREADSHEET_ID or "").strip()
    if not sid:
        raise RuntimeError("ULIXE_RCRM_GOOGLE_SPREADSHEET_ID non configurato.")

    name_tpl = effective_sheet_name_template()
    gid = settings.ULIXE_RCRM_GOOGLE_SHEET_GID
    col_range = (settings.ULIXE_RCRM_GOOGLE_COLUMN_RANGE or "A1:Q").strip()

    service = _build_sheets_service_from_info(info)
    title: str | None = None
    if name_tpl:
        title = sheet_title_for_period(period, name_tpl)
    elif gid is not None:
        title = _sheet_title_for_gid(service, sid, int(gid))
        if not title:
            raise RuntimeError(
                f"Tab con sheetId/gid {gid} non trovato nello spreadsheet {sid}. "
                "Verifica ULIXE_RCRM_GOOGLE_SHEET_GID."
            )
    else:
        raise RuntimeError(
            "Imposta ULIXE_RCRM_GOOGLE_SHEET_NAME_TEMPLATE (es. {mm}-ulixe-rcrm) "
            "oppure ULIXE_RCRM_GOOGLE_SHEET_GID per scegliere il foglio."
        )

    range_a1 = f"'{_escape_sheet_title(title)}'!{col_range}"
    return _fetch_values_with_retry(service, sid, range_a1)
