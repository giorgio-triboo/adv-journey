"""
Seeder per campagne Magellano.
Viene eseguito all'avvio dell'applicazione per assicurarsi che tutte le campagne siano presenti.
"""
from database import SessionLocal
from models import ManagedCampaign
import logging

logger = logging.getLogger(__name__)

# Campagne da gestire
CAMPAIGNS = [
    # Grandi Scuole
    {"campaign_id": "190", "name": "Grandi Scuole - 190"},
    {"campaign_id": "578", "name": "Grandi Scuole - 578"},
    {"campaign_id": "618", "name": "Grandi Scuole - 618"},
    {"campaign_id": "829", "name": "Grandi Scuole - 829"},
    {"campaign_id": "836", "name": "Grandi Scuole - 836"},
    {"campaign_id": "870", "name": "Grandi Scuole - 870"},
    # Fisioterapia
    {"campaign_id": "199", "name": "Fisioterapia - 199"},
    # Cepu
    {"campaign_id": "183", "name": "Cepu - 183"},
    # eCampus
    {"campaign_id": "188", "name": "eCampus - 188"},
    {"campaign_id": "200", "name": "eCampus - 200"},
    {"campaign_id": "872", "name": "eCampus - 872"},
    {"campaign_id": "889", "name": "eCampus - 889"},
    {"campaign_id": "909", "name": "eCampus - 909"},
    # Link Campus
    {"campaign_id": "423", "name": "Link Campus - 423"},
]

def seed_campaigns():
    """Aggiunge/aggiorna le campagne Magellano nel database."""
    db = SessionLocal()
    try:
        added = 0
        updated = 0
        
        for camp_data in CAMPAIGNS:
            existing = db.query(ManagedCampaign).filter(
                ManagedCampaign.campaign_id == camp_data["campaign_id"]
            ).first()
            
            if existing:
                # Update existing if name changed
                if existing.name != camp_data["name"]:
                    existing.name = camp_data["name"]
                    updated += 1
                # Ensure it's active
                if not existing.is_active:
                    existing.is_active = True
                    updated += 1
            else:
                new_campaign = ManagedCampaign(
                    campaign_id=camp_data["campaign_id"],
                    name=camp_data["name"],
                    is_active=True,
                    ulixe_ids=[]
                )
                db.add(new_campaign)
                added += 1
        
        db.commit()
        if added > 0 or updated > 0:
            logger.info(f"Campaigns seeder: {added} added, {updated} updated")
        return True
        
    except Exception as e:
        logger.error(f"Error seeding campaigns: {e}", exc_info=True)
        db.rollback()
        return False
    finally:
        db.close()
