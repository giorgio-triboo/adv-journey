"""
Script autonomo per marcare lead da sincronizzare con Meta Conversion API.
Verifica lead con status_category cambiato e imposta to_sync_meta = True.
Questo script può girare durante il giorno (08-18) per preparare le lead per la sync notturna.
"""
from sqlalchemy.orm import Session
from sqlalchemy import cast, String, and_, or_
from database import SessionLocal
from models import Lead
import logging

logger = logging.getLogger("services.sync")

# Processa le lead a batch per limitare memoria e persistere progressivamente
MARKER_BATCH_SIZE = 2000


def run(db: Session = None) -> dict:
    """
    Marca lead da sincronizzare con Meta CAPI.
    Verifica se status_category è diverso da last_meta_event_status.

    Returns: dict con statistiche {"marked": int, "skipped": int}
    """
    if db is None:
        db = SessionLocal()
        close_db = True
    else:
        close_db = False

    stats = {"marked": 0, "skipped": 0}

    status_mismatch = or_(
        cast(Lead.status_category, String) != Lead.last_meta_event_status,
        Lead.last_meta_event_status.is_(None),
    )
    base_filter = and_(
        status_mismatch,
        Lead.email.isnot(None),
        Lead.email != "",
    )

    try:
        last_id = 0
        total_seen = 0

        while True:
            batch = (
                db.query(Lead)
                .filter(base_filter, Lead.id > last_id)
                .order_by(Lead.id)
                .limit(MARKER_BATCH_SIZE)
                .all()
            )
            if not batch:
                break

            for lead in batch:
                total_seen += 1
                try:
                    current_status = (
                        lead.status_category.value
                        if hasattr(lead.status_category, "value")
                        else str(lead.status_category)
                    )
                    last_status = lead.last_meta_event_status or ""

                    if current_status != last_status:
                        lead.to_sync_meta = True
                        stats["marked"] += 1
                        logger.debug(
                            f"Lead {lead.id}: Marked for sync (status: {last_status} -> {current_status})"
                        )
                    else:
                        stats["skipped"] += 1

                except Exception as e:
                    logger.error(f"Error processing lead {lead.id}: {e}")
                    stats["skipped"] += 1

            last_id = batch[-1].id
            db.commit()

        logger.info(f"Meta Conversion Marker: Checked {total_seen} leads in batches of {MARKER_BATCH_SIZE}...")
        logger.info(f"Meta Conversion Marker ✅: {stats['marked']} marked, {stats['skipped']} skipped")

        from services.utils.alert_sender import send_sync_alert_if_needed

        send_sync_alert_if_needed(db, "meta_conversion_marker", True, stats)

    except Exception as e:
        logger.error(f"Meta Conversion Marker ❌: {e}", exc_info=True)
        db.rollback()
        try:
            from services.utils.alert_sender import send_sync_alert_if_needed

            send_sync_alert_if_needed(
                db,
                "meta_conversion_marker",
                False,
                stats,
                str(e),
            )
        except Exception:
            pass
    finally:
        if close_db:
            db.close()

    return stats
