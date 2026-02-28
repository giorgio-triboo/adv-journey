"""
Script standalone per:

- leggere le lead da Meta Lead Ads (endpoint /{AD_ID}/leads)
- fare match con le lead locali tramite email/telefono (hash Meta)
- valorizzare su Lead gli ID Meta stabili: meta_campaign_id, meta_adset_id, meta_ad_id

Uso (da root progetto, con Docker):

    docker compose exec backend python scripts/sync_meta_leads_from_ads.py

Prerequisiti:
- Variabile d'ambiente META_ACCESS_TOKEN configurata (come per gli altri sync Meta)
- Tabelle meta_accounts, meta_campaigns, meta_adsets, meta_ads già popolate
"""

import os
import sys
import logging
from typing import Optional, Dict, Any

# Assicura che /app (backend) sia nel path quando eseguito come script
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database import SessionLocal  # type: ignore
from models import Lead, MetaAd, MetaAdSet, MetaCampaign, MetaAccount  # type: ignore
from services.integrations.meta_marketing import MetaMarketingService  # type: ignore
from services.utils.crypto import (
    hash_email_for_meta,
    hash_phone_for_meta,
    decrypt_token,
)  # type: ignore

from facebook_business.adobjects.ad import Ad  # type: ignore


logger = logging.getLogger("scripts.sync_meta_leads_from_ads")
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


def _find_local_lead(db, email: Optional[str], phone: Optional[str]) -> Optional[Lead]:
    """
    Trova una Lead locale sulla base di email/telefono (hashati secondo specifiche Meta).

    Strategia:
    - se ho email: match diretto su Lead.email
    - altrimenti, se ho telefono: match su Lead.phone
    - se trovo più di una lead, preferisco quella più recente
    """
    if email:
        email_hash = hash_email_for_meta(email)
        if email_hash:
            q = (
                db.query(Lead)
                .filter(Lead.email == email_hash)
                .order_by(Lead.created_at.desc())
            )
            leads = q.all()
            if len(leads) == 1:
                return leads[0]
            if len(leads) > 1:
                logger.warning(
                    "Trovate %s lead con stessa email hashata; uso la più recente",
                    len(leads),
                )
                return leads[0]

    if phone:
        phone_hash = hash_phone_for_meta(phone)
        if phone_hash:
            q = (
                db.query(Lead)
                .filter(Lead.phone == phone_hash)
                .order_by(Lead.created_at.desc())
            )
            leads = q.all()
            if len(leads) == 1:
                return leads[0]
            if len(leads) > 1:
                logger.warning(
                    "Trovate %s lead con stesso telefono hashato; uso la più recente",
                    len(leads),
                )
                return leads[0]

    return None


def sync_meta_leads_from_ads(
    db, only_missing: bool = True, limit_ads: Optional[int] = None
) -> Dict[str, int]:
    """
    Legge le lead da tutti gli Ad Meta presenti a DB e sincronizza gli ID Meta sulle Lead locali.

    Args:
        db: Sessione DB SQLAlchemy.
        only_missing: se True, aggiorna solo lead che non hanno ancora meta_campaign_id/meta_ad_id.
        limit_ads: se valorizzato, limita il numero di ads elaborati (per test).

    Returns:
        Statistiche: dict con conteggi vari.
    """
    stats = {
        "ads_total": 0,
        "ads_processed": 0,
        "meta_leads_fetched": 0,
        "local_leads_matched": 0,
        "local_leads_already_linked": 0,
        "local_leads_not_found": 0,
        "errors": 0,
    }

    # Non usare il token legacy da META_ACCESS_TOKEN: inizializza il SDK per
    # ogni account Meta in base al token salvato in meta_accounts.
    current_meta_account_id: Optional[int] = None
    current_access_token: Optional[str] = None

    # Seleziona tutti gli ads legati ad account attivi
    ads_query = (
        db.query(MetaAd)
        .join(MetaAdSet)
        .join(MetaCampaign)
        .join(MetaAccount)
        .filter(MetaAccount.is_active == True)  # noqa: E712
    )

    if limit_ads:
        ads_query = ads_query.limit(limit_ads)

    ads = ads_query.all()
    stats["ads_total"] = len(ads)
    logger.info("Trovati %s MetaAd da elaborare", stats["ads_total"])

    for idx, meta_ad in enumerate(ads, 1):
        stats["ads_processed"] += 1
        logger.info(
            "[%s/%s] Ad %s (%s)",
            idx,
            stats["ads_total"],
            meta_ad.ad_id,
            meta_ad.name,
        )

        try:
            # Determina l'account Meta collegato a questo Ad e inizializza il SDK
            adset: Optional[MetaAdSet] = meta_ad.adset
            campaign: Optional[MetaCampaign] = adset.campaign if adset else None
            account: Optional[MetaAccount] = campaign.account if campaign else None

            if not account or not account.access_token:
                logger.error(
                    "Nessun MetaAccount con token trovato per ad %s: salta sync per questo Ad",
                    meta_ad.ad_id,
                )
                stats["errors"] += 1
                continue

            if account.id != current_meta_account_id:
                try:
                    current_access_token = decrypt_token(account.access_token)
                except Exception as e:
                    logger.error(
                        "Impossibile decriptare il token Meta per account %s (ad %s): %s",
                        account.account_id,
                        meta_ad.ad_id,
                        e,
                    )
                    stats["errors"] += 1
                    continue

                meta_service = MetaMarketingService(access_token=current_access_token)
                if not meta_service.access_token:
                    logger.error(
                        "Token Meta vuoto o non valido per account %s (ad %s): impossibile chiamare Meta API",
                        account.account_id,
                        meta_ad.ad_id,
                    )
                    stats["errors"] += 1
                    continue

                current_meta_account_id = account.id

            ad_obj = Ad(meta_ad.ad_id)

            # fields base per i lead
            fields = ["id", "ad_id", "form_id", "created_time", "field_data"]

            # NB: la business SDK gestisce la paginazione tramite il cursor
            leads_cursor = ad_obj.get_leads(params={}, fields=fields)

            for lead_obj in leads_cursor:
                stats["meta_leads_fetched"] += 1
                lead_id = lead_obj.get("id")
                field_data = lead_obj.get("field_data", [])

                contact = _extract_contact_from_field_data(field_data)
                email = contact["email"]
                phone = contact["phone"]

                if not email and not phone:
                    logger.info(
                        "Lead Meta %s senza email/telefono, impossibile fare match", lead_id
                    )
                    stats["local_leads_not_found"] += 1
                    continue

                local_lead = _find_local_lead(db, email=email, phone=phone)
                if not local_lead:
                    logger.info(
                        "Nessuna lead locale trovata per lead Meta %s (email=%s, phone=%s)",
                        lead_id,
                        email,
                        phone,
                    )
                    stats["local_leads_not_found"] += 1
                    continue

                if only_missing and (
                    local_lead.meta_campaign_id
                    or local_lead.meta_adset_id
                    or local_lead.meta_ad_id
                ):
                    stats["local_leads_already_linked"] += 1
                    continue

                # Aggiorna gli ID Meta sulla lead
                if campaign:
                    local_lead.meta_campaign_id = campaign.campaign_id
                if adset:
                    local_lead.meta_adset_id = adset.adset_id
                local_lead.meta_ad_id = meta_ad.ad_id
                local_lead.meta_correlation_status = "found_via_leads_api"

                stats["local_leads_matched"] += 1

            # Commit dopo ogni ad per semplicità (si può ottimizzare a batch)
            try:
                db.commit()
            except Exception as commit_err:
                logger.error(
                    "Errore durante commit per ad %s: %s", meta_ad.ad_id, commit_err
                )
                db.rollback()
                stats["errors"] += 1

        except Exception as e:
            logger.error("Errore durante sync lead per ad %s: %s", meta_ad.ad_id, e)
            stats["errors"] += 1
            db.rollback()

    logger.info("Sync completata. Stats: %s", stats)
    return stats


def main():
    db = SessionLocal()
    try:
        logger.info("Avvio sync lead da Meta Lead Ads...")
        stats = sync_meta_leads_from_ads(db, only_missing=True)
        logger.info("Sync completata. Risultato finale: %s", stats)
    finally:
        db.close()


if __name__ == "__main__":
    main()

