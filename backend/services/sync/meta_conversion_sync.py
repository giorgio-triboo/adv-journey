"""
Job autonomo per invio eventi Meta Conversion API.
Invia eventi per lead marcate con to_sync_meta = True.
Recupera token dall'account Meta corretto e adset dal mapping campagna Magellano.
"""
from sqlalchemy.orm import Session, joinedload
from database import SessionLocal
from services.integrations.meta import MetaService
from services.utils.crypto import decrypt_token
from models import Lead, StatusCategory, MetaAccount, MetaCampaign, ManagedCampaign
from config import settings
import logging
import time

logger = logging.getLogger('services.sync')


def _build_magellano_dataset_map(db: Session) -> dict[str, str]:
    """
    Una query: tutte le campagne gestite attive; indice magellano_id (str) -> meta_dataset_id.
    In caso di più righe con lo stesso id Magellano, vince la prima per ManagedCampaign.id (stabile).
    """
    mapping: dict[str, str] = {}
    rows = (
        db.query(ManagedCampaign)
        .filter(ManagedCampaign.is_active == True)
        .order_by(ManagedCampaign.id)
        .all()
    )
    for mc in rows:
        if not mc.meta_dataset_id or not mc.magellano_ids:
            continue
        for mid in mc.magellano_ids:
            key = str(mid)
            if key not in mapping:
                mapping[key] = mc.meta_dataset_id
    return mapping


def _preload_meta_campaigns_by_id(db: Session, campaign_ids: set[str]) -> dict[str, MetaCampaign]:
    """Una query con eager load account; lookup O(1) per meta_campaign_id."""
    if not campaign_ids:
        return {}
    rows = (
        db.query(MetaCampaign)
        .filter(MetaCampaign.campaign_id.in_(campaign_ids))
        .options(joinedload(MetaCampaign.account))
        .all()
    )
    return {c.campaign_id: c for c in rows}


def _load_shared_meta_account(db: Session) -> tuple[MetaAccount | None, str | None]:
    """Account condiviso (user_id NULL) attivo con token; ordinamento deterministico."""
    acc = (
        db.query(MetaAccount)
        .filter(MetaAccount.is_active == True, MetaAccount.user_id.is_(None))
        .order_by(MetaAccount.id)
        .first()
    )
    if not acc or not acc.access_token:
        return (None, None)
    try:
        return (acc, decrypt_token(acc.access_token))
    except Exception as e:
        logger.error(f"Error decrypting shared Meta account token: {e}")
        return (acc, None)


def _resolve_meta_for_lead(
    lead: Lead,
    meta_campaign_by_id: dict[str, MetaCampaign],
    account_token_cache: dict[int, str],
    shared_account: MetaAccount | None,
    shared_token: str | None,
    pixel_id: str,
) -> tuple[MetaAccount | None, str | None, str]:
    """
    Risolve (account, access_token, pixel_id) per una lead usando strutture precaricate.
    """
    try:
        cid = lead.meta_campaign_id
        if cid:
            mc = meta_campaign_by_id.get(cid)
            if mc and mc.account and mc.account.is_active and mc.account.access_token:
                aid = mc.account.id
                if aid not in account_token_cache:
                    account_token_cache[aid] = decrypt_token(mc.account.access_token)
                return (mc.account, account_token_cache[aid], pixel_id)

        if shared_account and shared_token:
            return (shared_account, shared_token, pixel_id)

        if settings.META_ACCESS_TOKEN:
            return (None, settings.META_ACCESS_TOKEN, pixel_id)

        return (None, None, pixel_id)
    except Exception as e:
        logger.error(f"Error getting Meta account for lead {lead.id}: {e}")
        return (None, None, pixel_id)


def run(db: Session = None) -> dict:
    """
    Esegue il job di invio eventi Meta Conversion API.
    Cerca solo lead con to_sync_meta = True.

    Returns: dict con statistiche {"events_sent": int, "errors": int, "skipped": int}
    """
    if db is None:
        db = SessionLocal()
        close_db = True
    else:
        close_db = False

    stats = {"events_sent": 0, "errors": 0, "skipped": 0}
    pixel_id = settings.META_PIXEL_ID or ""

    try:
        # Get leads marcate per sync (email non nulla e non vuota)
        leads_for_events = (
            db.query(Lead)
            .filter(
                Lead.to_sync_meta == True,
                Lead.email.isnot(None),
                Lead.email != "",
            )
            .limit(500)
            .all()
        )

        logger.info(f"Meta Conversion Sync: Processing {len(leads_for_events)} leads marked for sync...")

        # Precaricamento: mapping Magellano -> dataset (una query)
        magellano_dataset_map = _build_magellano_dataset_map(db)

        # Precaricamento: MetaCampaign + account per tutti i campaign_id del batch (una query)
        campaign_ids = {l.meta_campaign_id for l in leads_for_events if l.meta_campaign_id}
        meta_campaign_by_id = _preload_meta_campaigns_by_id(db, campaign_ids)

        # Account condiviso e token (una query + decrypt)
        shared_account, shared_token = _load_shared_meta_account(db)

        # Cache decrypt per account_id usati nel batch
        account_token_cache: dict[int, str] = {}

        for lead in leads_for_events:
            try:
                event_name = "LeadStatus_Update"

                mag_cat = lead.magellano_status_category
                if mag_cat == StatusCategory.IN_LAVORAZIONE:
                    mag_code = "magellano_approved"
                elif mag_cat == StatusCategory.RIFIUTATO:
                    mag_code = "magellano_refused"
                else:
                    mag_code = "magellano_unknown"

                ulixe_cat = lead.ulixe_status_category
                if ulixe_cat == StatusCategory.IN_LAVORAZIONE:
                    ulixe_code = "ulixe_in_lavorazione"
                elif ulixe_cat == StatusCategory.RIFIUTATO:
                    ulixe_code = "ulixe_rifiutato"
                elif ulixe_cat == StatusCategory.CRM:
                    ulixe_code = "ulixe_crm"
                elif ulixe_cat == StatusCategory.FINALE:
                    ulixe_code = "ulixe_finale"
                elif ulixe_cat == StatusCategory.UNKNOWN:
                    ulixe_code = "ulixe_unknown"
                else:
                    ulixe_code = None

                if ulixe_cat in (StatusCategory.IN_LAVORAZIONE, StatusCategory.CRM, StatusCategory.FINALE):
                    ws_status_code = "ws_approved"
                elif ulixe_cat == StatusCategory.RIFIUTATO:
                    ws_status_code = "ws_refused"
                else:
                    ws_status_code = "ws_unknown"

                if ulixe_cat is not None:
                    status_source = "ulixe"
                    status_stage = "uscita_ws"
                    status_code = ws_status_code
                else:
                    status_source = "magellano"
                    status_stage = "ingresso_magellano"
                    status_code = mag_code

                account, access_token, resolved_pixel = _resolve_meta_for_lead(
                    lead,
                    meta_campaign_by_id,
                    account_token_cache,
                    shared_account,
                    shared_token,
                    pixel_id,
                )

                if not access_token:
                    logger.warning(f"Lead {lead.id}: No Meta access token available, skipping")
                    lead.meta_correlation_status = "no_credentials"
                    lead.to_sync_meta = False
                    stats["skipped"] += 1
                    continue

                dataset_id = None
                if lead.magellano_campaign_id:
                    dataset_id = magellano_dataset_map.get(str(lead.magellano_campaign_id))

                target_id = dataset_id or resolved_pixel

                if not target_id:
                    logger.warning(f"Lead {lead.id}: No dataset_id or pixel_id available, skipping")
                    lead.meta_correlation_status = "no_dataset"
                    lead.to_sync_meta = False
                    stats["skipped"] += 1
                    continue

                meta_service = MetaService(access_token=access_token, pixel_id=resolved_pixel, dataset_id=dataset_id)

                additional_data = {
                    "status": lead.current_status,
                    "status_category": lead.status_category.value
                    if hasattr(lead.status_category, "value")
                    else str(lead.status_category),
                    "status_source": status_source,
                    "status_stage": status_stage,
                    "status_code": status_code,
                    "magellano_status_code": mag_code,
                    "magellano_status_raw": lead.magellano_status_raw,
                    "magellano_status_category": mag_cat.value
                    if hasattr(mag_cat, "value")
                    else (str(mag_cat) if mag_cat is not None else None),
                    "ws_status_code": ws_status_code,
                    "ulixe_status_code": ulixe_code,
                    "ulixe_status_raw": lead.ulixe_status,
                    "ulixe_status_category": ulixe_cat.value
                    if hasattr(ulixe_cat, "value")
                    else (str(ulixe_cat) if ulixe_cat is not None else None),
                    "lead_id": lead.id,
                    "magellano_id": lead.magellano_id,
                    "external_user_id": lead.external_user_id,
                    "meta_campaign_id": lead.meta_campaign_id,
                    "meta_adset_id": lead.meta_adset_id,
                    "meta_ad_id": lead.meta_ad_id,
                    "brand": lead.brand,
                    "campaign_name": lead.campaign_name,
                }

                result = meta_service.send_custom_event(
                    event_name=event_name,
                    lead_data={
                        "email": lead.email,
                        "phone": lead.phone,
                        "province": getattr(lead, "province", "") or "",
                    },
                    additional_data=additional_data,
                    adset_id=lead.meta_adset_id,
                    campaign_id=lead.meta_campaign_id,
                    ad_id=lead.meta_ad_id,
                )

                if result:
                    stats["events_sent"] += 1
                    lead.to_sync_meta = False
                    lead.last_meta_event_status = (
                        lead.status_category.value
                        if hasattr(lead.status_category, "value")
                        else str(lead.status_category)
                    )
                    lead.meta_correlation_status = "found" if dataset_id else "sent_no_dataset"
                    logger.debug(
                        f"Lead {lead.id}: Event {event_name} sent successfully to dataset {dataset_id or 'pixel fallback'}"
                    )
                else:
                    stats["errors"] += 1
                    lead.meta_correlation_status = "error"
                    logger.warning(f"Lead {lead.id}: Failed to send event {event_name}")

                time.sleep(1.0)

            except Exception as e:
                stats["errors"] += 1
                lead.meta_correlation_status = "error"
                logger.error(f"Error sending Meta event for lead {lead.id}: {e}", exc_info=True)

        db.commit()
        logger.info(
            f"Meta Conversion Sync ✅: {stats['events_sent']} events sent, {stats['errors']} errors, {stats['skipped']} skipped"
        )

        from services.utils.alert_sender import send_sync_alert_if_needed

        send_sync_alert_if_needed(db, "meta_conversion_sync", True, stats)

    except Exception as e:
        logger.error(f"Meta Conversion Sync ❌: {e}", exc_info=True)
        stats["errors"] += 1

        from services.utils.alert_sender import send_sync_alert_if_needed

        send_sync_alert_if_needed(db, "meta_conversion_sync", False, stats, str(e))
    finally:
        if close_db:
            db.close()

    return stats
