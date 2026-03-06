"""
Servizio per correlazione automatica Lead ↔ Meta Marketing.
Usa i campi Facebook estratti da Magellano per fare match con i dati Meta.
"""
from sqlalchemy.orm import Session
from models import Lead, MetaCampaign, MetaAdSet, MetaAd
import logging

logger = logging.getLogger(__name__)

class LeadCorrelationService:
    """
    Servizio per correlare automaticamente lead con dati Meta Marketing.
    
    Nuova strategia (robusta ai rename):
    1. Se disponibili, usa gli ID Meta già presenti sulla lead:
       - lead.meta_campaign_id  → MetaCampaign.campaign_id
       - lead.meta_adset_id     → MetaAdSet.adset_id
       - lead.meta_ad_id        → MetaAd.ad_id
    2. Solo in assenza di ID, fallback ai nomi Magellano:
       - facebook_campaign_name → MetaCampaign.name
       - facebook_ad_set        → MetaAdSet.name
       - facebook_ad_name       → MetaAd.name
    """
    
    def correlate_lead_with_meta(self, lead: Lead, db: Session) -> bool:
        """
        Correla una lead con i dati Meta Marketing.
        
        Returns: True se è stata trovata una correlazione (via ID o nome), False altrimenti.
        """
        # Se non abbiamo né ID Meta né nomi Facebook utili, non possiamo fare nulla
        if not (
            lead.meta_campaign_id
            or lead.meta_adset_id
            or lead.meta_ad_id
            or lead.facebook_campaign_name
            or lead.facebook_ad_name
        ):
            return False
        
        correlated = False
        
        # 1. Match Campaign (preferisci ID se già presente)
        meta_campaign = None
        if lead.meta_campaign_id:
            meta_campaign = (
                db.query(MetaCampaign)
                .filter(MetaCampaign.campaign_id == lead.meta_campaign_id)
                .first()
            )
            if meta_campaign:
                correlated = True
        elif lead.facebook_campaign_name:
            meta_campaign = (
                db.query(MetaCampaign)
                .filter(MetaCampaign.name.ilike(f"%{lead.facebook_campaign_name}%"))
                .first()
            )
            if meta_campaign:
                lead.meta_campaign_id = meta_campaign.campaign_id
                correlated = True
                logger.debug(
                    f"Lead {lead.id}: Matched campaign '{lead.facebook_campaign_name}' → {meta_campaign.campaign_id}"
                )
        
        # 2. Match AdSet (preferisci ID, altrimenti nome all'interno della campagna)
        meta_adset = None
        if lead.meta_adset_id:
            meta_adset = (
                db.query(MetaAdSet)
                .filter(MetaAdSet.adset_id == lead.meta_adset_id)
                .first()
            )
            if meta_adset:
                correlated = True
        elif meta_campaign and lead.facebook_ad_set:
            meta_adset = (
                db.query(MetaAdSet)
                .filter(
                    MetaAdSet.campaign_id == meta_campaign.id,
                    MetaAdSet.name.ilike(f"%{lead.facebook_ad_set}%"),
                )
                .first()
            )
            if meta_adset:
                lead.meta_adset_id = meta_adset.adset_id
                correlated = True
                logger.debug(
                    f"Lead {lead.id}: Matched adset '{lead.facebook_ad_set}' → {meta_adset.adset_id}"
                )
        
        # 3. Match Ad (preferisci ID, altrimenti nome all'interno dell'adset)
        if lead.meta_ad_id:
            meta_ad = (
                db.query(MetaAd)
                .filter(MetaAd.ad_id == lead.meta_ad_id)
                .first()
            )
            if meta_ad:
                correlated = True
        elif meta_adset and lead.facebook_ad_name:
            meta_ad = (
                db.query(MetaAd)
                .filter(
                    MetaAd.adset_id == meta_adset.id,
                    MetaAd.name.ilike(f"%{lead.facebook_ad_name}%"),
                )
                .first()
            )
            if meta_ad:
                lead.meta_ad_id = meta_ad.ad_id
                correlated = True
                logger.debug(
                    f"Lead {lead.id}: Matched ad '{lead.facebook_ad_name}' → {meta_ad.ad_id}"
                )
        
        return correlated
    
    def correlate_batch(self, leads: list[Lead], db: Session) -> dict:
        """
        Correla un batch di lead con i dati Meta.
        
        Returns: dict con statistiche {"correlated": int, "not_found": int}
        """
        stats = {"correlated": 0, "not_found": 0}
        
        for lead in leads:
            if self.correlate_lead_with_meta(lead, db):
                stats["correlated"] += 1
            else:
                stats["not_found"] += 1
        
        db.commit()
        return stats
