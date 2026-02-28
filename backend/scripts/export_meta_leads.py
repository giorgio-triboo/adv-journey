"""
Export semplice di TUTTE le lead Meta Lead Ads legate agli Ad presenti nel DB locale.

Non fa nessun match o update sul database: si limita a leggere da Meta e scrivere un CSV.

Uso tipico (da root progetto, con container backend in esecuzione):

    docker compose exec backend python scripts/export_meta_leads.py

Output:
- File CSV: backend/exports/meta_leads.csv
  con colonne: meta_lead_id, created_time, email, phone, ad_id, ad_name,
  adset_id, adset_name, campaign_id, campaign_name, account_id, account_name, form_id
"""

import os
import sys
import csv
import logging
import argparse
from datetime import datetime, date
from typing import Optional, Dict, Any

# Assicura che la cartella backend sia nel sys.path quando eseguito come script
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import SessionLocal  # type: ignore
from models import MetaAd, MetaAdSet, MetaCampaign, MetaAccount  # type: ignore
from services.integrations.meta_marketing import MetaMarketingService  # type: ignore
from services.utils.crypto import decrypt_token  # type: ignore

from facebook_business.adobjects.ad import Ad  # type: ignore


logger = logging.getLogger("scripts.export_meta_leads")
logging.basicConfig(level=logging.INFO)


def _extract_contact_from_field_data(field_data: Any) -> Dict[str, Optional[str]]:
    """
    Estrae email/telefono da field_data di Meta Lead Ads.

    field_data è una lista di dict:
        [{"name": "email", "values": ["foo@example.com"]}, ...]
    """
    email: Optional[str] = None
    phone: Optional[str] = None

    if not isinstance(field_data, list):
        return {"email": None, "phone": None}

    for item in field_data:
        try:
            name = (item.get("name") or "").lower()
            values = item.get("values") or []
            if not values:
                continue
            value = values[0]

            if name == "email" and not email:
                email = value
            elif name in {"phone_number", "phone", "phone_number_raw"} and not phone:
                phone = value
        except Exception:
            # Non blocchiamo per un singolo campo malformato
            continue

    return {"email": email, "phone": phone}


def export_meta_leads(
    db,
    output_path: str,
    limit_ads: Optional[int] = None,
    limit_leads_per_ad: Optional[int] = None,
    account_id: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> int:
    """
    Esporta tutte le lead Meta Lead Ads per gli Ad presenti nel DB locale.

    Args:
        db: Sessione DB SQLAlchemy.
        output_path: percorso file CSV di output.
        limit_ads: opzionale, limite massimo di ads da elaborare (per test).
        limit_leads_per_ad: opzionale, limite massimo di lead per ogni ad (per test).

    Returns:
        Numero totale di lead esportate.
    """
    # Recupera token Meta dall'account specifico, senza usare META_ACCESS_TOKEN legacy
    if not account_id:
        logger.error(
            "account_id obbligatorio per export lead: l'uso di META_ACCESS_TOKEN legacy è deprecato."
        )
        return 0

    logger.info("Inizializzo Meta SDK usando il token dell'account %s da meta_accounts", account_id)
    meta_account = (
        db.query(MetaAccount)
        .filter(MetaAccount.account_id == account_id, MetaAccount.is_active == True)  # noqa: E712
        .first()
    )
    if not meta_account or not meta_account.access_token:
        logger.error(
            "Nessun MetaAccount attivo con token trovato per account_id=%s. "
            "Configura l'account da /settings/meta-accounts prima di eseguire l'export.",
            account_id,
        )
        return 0

    try:
        access_token = decrypt_token(meta_account.access_token)
    except Exception as e:
        logger.error(
            "Impossibile decriptare il token Meta per account_id=%s: %s", account_id, e
        )
        return 0

    meta_service = MetaMarketingService(access_token=access_token)
    if not meta_service.access_token:
        logger.error(
            "Token Meta vuoto o non valido per account_id=%s: impossibile chiamare Meta API",
            account_id,
        )
        return 0

    # Seleziona tutti gli ads legati ad account attivi
    ads_query = (
        db.query(MetaAd)
        .join(MetaAdSet)
        .join(MetaCampaign)
        .join(MetaAccount)
        .filter(MetaAccount.is_active == True)  # noqa: E712
    )

    # Filtro per account specifico, se richiesto
    if account_id:
        logger.info("Filtro per account_id Meta: %s", account_id)
        ads_query = ads_query.filter(MetaAccount.account_id == account_id)

    if limit_ads:
        ads_query = ads_query.limit(limit_ads)

    ads = ads_query.all()
    logger.info("Trovati %s MetaAd da elaborare", len(ads))

    total_leads = 0

    # Prepara cartella di output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile, delimiter=";")
        writer.writerow(
            [
                "meta_lead_id",
                "created_time",
                "email",
                "phone",
                "ad_id",
                "ad_name",
                "adset_id",
                "adset_name",
                "campaign_id",
                "campaign_name",
                "account_id",
                "account_name",
                "form_id",
            ]
        )

        for idx, meta_ad in enumerate(ads, 1):
            logger.info(
                "[%s/%s] Leggo lead per Ad %s (%s)",
                idx,
                len(ads),
                meta_ad.ad_id,
                meta_ad.name,
            )

            adset: Optional[MetaAdSet] = meta_ad.adset
            campaign: Optional[MetaCampaign] = adset.campaign if adset else None
            account: Optional[MetaAccount] = campaign.account if campaign else None

            try:
                ad_obj = Ad(meta_ad.ad_id)

                fields = ["id", "ad_id", "form_id", "created_time", "field_data"]
                leads_cursor = ad_obj.get_leads(params={}, fields=fields)

                for lead_index, lead_obj in enumerate(leads_cursor, 1):
                    if limit_leads_per_ad and lead_index > limit_leads_per_ad:
                        break

                    lead_id = lead_obj.get("id")
                    created_time = lead_obj.get("created_time")
                    form_id = lead_obj.get("form_id")
                    field_data = lead_obj.get("field_data", [])

                    # Parse created_time per eventuale filtro data
                    lead_date_ok = True
                    lead_dt: Optional[datetime] = None
                    if created_time:
                        try:
                            # created_time tipico: "2026-02-25T14:30:12+0000" o "2026-02-25T14:30:12Z"
                            ts = str(created_time)
                            if ts.endswith("Z"):
                                ts = ts.replace("Z", "+00:00")
                            # Togli eventuale offset nel formato +0000
                            if "+" in ts and ts.rsplit("+", 1)[1].isdigit():
                                # "2026-02-25T14:30:12+0000" -> "2026-02-25T14:30:12"
                                ts = ts.rsplit("+", 1)[0]
                            lead_dt = datetime.fromisoformat(ts)
                        except Exception:
                            # Se non riusciamo a fare parsing, non applichiamo il filtro data
                            lead_dt = None

                    if (date_from or date_to) and lead_dt is not None:
                        lead_d = lead_dt.date()
                        if date_from and lead_d < date_from:
                            lead_date_ok = False
                        if date_to and lead_d > date_to:
                            lead_date_ok = False

                    if not lead_date_ok:
                        continue

                    contact = _extract_contact_from_field_data(field_data)

                    writer.writerow(
                        [
                            lead_id,
                            created_time,
                            contact.get("email") or "",
                            contact.get("phone") or "",
                            meta_ad.ad_id or "",
                            meta_ad.name or "",
                            adset.adset_id if adset else "",
                            adset.name if adset else "",
                            campaign.campaign_id if campaign else "",
                            campaign.name if campaign else "",
                            account.account_id if account else "",
                            account.name if account else "",
                            form_id or "",
                        ]
                    )
                    total_leads += 1

            except Exception as e:
                logger.error("Errore durante lettura lead per ad %s: %s", meta_ad.ad_id, e)

    logger.info("Export completato. Lead totali esportate: %s", total_leads)
    logger.info("File CSV: %s", output_path)
    return total_leads


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Export di TUTTE le lead Meta Lead Ads legate agli Ad presenti nel DB locale.\n"
            "Puoi filtrare per account Meta e per data creazione lead."
        )
    )
    parser.add_argument(
        "--account-id",
        help="ID account Meta (es. 123456789 o act_123456789). Se omesso, usa tutti gli account attivi.",
        default=None,
    )
    parser.add_argument(
        "--date-from",
        help="Data inizio (YYYY-MM-DD o DD/MM/YYYY) su created_time Meta lead (inclusiva).",
        default=None,
    )
    parser.add_argument(
        "--date-to",
        help="Data fine (YYYY-MM-DD o DD/MM/YYYY) su created_time Meta lead (inclusiva).",
        default=None,
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Percorso file CSV di output (default: exports/meta_leads.csv).",
        default=None,
    )
    parser.add_argument(
        "--limit-ads",
        type=int,
        default=None,
        help="Limite massimo di ads da elaborare (per test).",
    )
    parser.add_argument(
        "--limit-leads-per-ad",
        type=int,
        default=None,
        help="Limite massimo di lead per ad (per test).",
    )

    args = parser.parse_args()

    # Normalizza account_id (rimuovi eventuale prefisso act_)
    account_id: Optional[str] = None
    if args.account_id:
        raw = str(args.account_id).strip()
        account_id = raw.replace("act_", "") if raw.startswith("act_") else raw

    # Parse date_from / date_to come date (ignora orario)
    def _parse_date(value: Optional[str]) -> Optional[date]:
        if not value:
            return None
        v = value.strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(v, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Formato data non valido: {value}. Usa YYYY-MM-DD o DD/MM/YYYY.")

    date_from: Optional[date] = None
    date_to: Optional[date] = None
    try:
        date_from = _parse_date(args.date_from)
        date_to = _parse_date(args.date_to)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    if date_from and date_to and date_from > date_to:
        logger.error("date-from (%s) è successiva a date-to (%s)", date_from, date_to)
        sys.exit(1)

    exports_dir = os.path.join(PROJECT_ROOT, "exports")
    if args.output:
        output_path = args.output
        # Se è un path relativo, riportalo rispetto alla root progetto
        if not os.path.isabs(output_path):
            output_path = os.path.join(PROJECT_ROOT, output_path)
    else:
        os.makedirs(exports_dir, exist_ok=True)
        output_path = os.path.join(exports_dir, "meta_leads.csv")

    db = SessionLocal()
    try:
        logger.info(
            "Avvio export lead Meta verso %s (account_id=%s, date_from=%s, date_to=%s)",
            output_path,
            account_id or "TUTTI",
            date_from,
            date_to,
        )
        total = export_meta_leads(
            db,
            output_path=output_path,
            limit_ads=args.limit_ads,
            limit_leads_per_ad=args.limit_leads_per_ad,
            account_id=account_id,
            date_from=date_from,
            date_to=date_to,
        )
        logger.info("Export terminato. Lead totali: %s", total)
    finally:
        db.close()


if __name__ == "__main__":
    main()

