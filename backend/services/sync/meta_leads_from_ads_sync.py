"""
Match lead Meta Lead Ads → Lead Magellano (meta_campaign_id / meta_adset_id / meta_ad_id)
tramite API get_leads + hash email/telefono.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from models import Lead, MetaAccount, MetaAd, MetaAdSet, MetaCampaign
from services.integrations.meta_marketing import MetaMarketingService
from services.utils.crypto import decrypt_token, hash_email_for_meta, hash_phone_for_meta

from facebook_business.adobjects.ad import Ad

logger = logging.getLogger("services.sync.meta_leads_from_ads_sync")


def _extract_contact_from_field_data(field_data: Any) -> Dict[str, Optional[str]]:
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
            continue

    return {"email": email, "phone": phone}


def _find_local_lead(db, email: Optional[str], phone: Optional[str]) -> Optional[Lead]:
    if email:
        email_hash = hash_email_for_meta(email)
        if email_hash:
            q = (
                db.query(Lead)
                .filter(Lead.email == email_hash)
                .order_by(Lead.created_at.desc())
            )
            leads = q.all()
            if len(leads) >= 1:
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
            if len(leads) >= 1:
                if len(leads) > 1:
                    logger.warning(
                        "Trovate %s lead con stesso telefono hashato; uso la più recente",
                        len(leads),
                    )
                return leads[0]

    return None


def sync_meta_leads_from_ads(
    db,
    only_missing: bool = True,
    limit_ads: Optional[int] = None,
) -> Dict[str, int]:
    """
    Legge le lead da tutti gli Ad Meta presenti a DB e sincronizza gli ID Meta sulle Lead locali.
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

    current_meta_account_id: Optional[int] = None
    current_access_token: Optional[str] = None

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
                        "Token Meta vuoto o non valido per account %s (ad %s)",
                        account.account_id,
                        meta_ad.ad_id,
                    )
                    stats["errors"] += 1
                    continue

                current_meta_account_id = account.id

            ad_obj = Ad(meta_ad.ad_id)
            fields = ["id", "ad_id", "form_id", "created_time", "field_data"]
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

                if campaign:
                    local_lead.meta_campaign_id = campaign.campaign_id
                if adset:
                    local_lead.meta_adset_id = adset.adset_id
                local_lead.meta_ad_id = meta_ad.ad_id
                local_lead.meta_correlation_status = "found_via_leads_api"

                stats["local_leads_matched"] += 1

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
