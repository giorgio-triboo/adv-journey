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
    
    Strategia di matching:
    - facebook_campaign_name → MetaCampaign.name
    - facebook_ad_set → MetaAdSet.name
    - facebook_ad_name → MetaAd.name
    - facebook_id → MetaAd.ad_id (se disponibile)
    """
    
    def correlate_lead_with_meta(self, lead: Lead, db: Session) -> bool:
        """
        Correla una lead con i dati Meta Marketing usando i campi Facebook da Magellano.
        
        Returns: True se è stata trovata una correlazione, False altrimenti
        """
        if not lead.facebook_campaign_name and not lead.facebook_ad_name:
            return False
        
        correlated = False
        
        # 1. Match Campaign
        if lead.facebook_campaign_name:
            meta_campaign = db.query(MetaCampaign).filter(
                MetaCampaign.name.ilike(f"%{lead.facebook_campaign_name}%")
            ).first()
            
            if meta_campaign:
                lead.meta_campaign_id = meta_campaign.campaign_id
                correlated = True
                logger.debug(f"Lead {lead.id}: Matched campaign '{lead.facebook_campaign_name}' → {meta_campaign.campaign_id}")
        
        # 2. Match AdSet (se abbiamo campaign_id)
        if lead.meta_campaign_id and lead.facebook_ad_set:
            meta_campaign = db.query(MetaCampaign).filter(
                MetaCampaign.campaign_id == lead.meta_campaign_id
            ).first()
            
            if meta_campaign:
                meta_adset = db.query(MetaAdSet).filter(
                    MetaAdSet.campaign_id == meta_campaign.id,
                    MetaAdSet.name.ilike(f"%{lead.facebook_ad_set}%")
                ).first()
                
                if meta_adset:
                    lead.meta_adset_id = meta_adset.adset_id
                    correlated = True
                    logger.debug(f"Lead {lead.id}: Matched adset '{lead.facebook_ad_set}' → {meta_adset.adset_id}")
        
        # 3. Match Ad (usa solo facebook_ad_name, facebook_id è l'ID utente)
        meta_ad = None
        if lead.meta_adset_id:
            meta_adset = db.query(MetaAdSet).filter(
                MetaAdSet.adset_id == lead.meta_adset_id
            ).first()
            
            if meta_adset and lead.facebook_ad_name:
                # Match usando solo il nome dell'ad (facebook_id è l'ID utente, non l'ID ad)
                meta_ad = db.query(MetaAd).filter(
                    MetaAd.adset_id == meta_adset.id,
                    MetaAd.name.ilike(f"%{lead.facebook_ad_name}%")
                ).first()
                
                if meta_ad:
                    lead.meta_ad_id = meta_ad.ad_id
                    correlated = True
                    logger.debug(f"Lead {lead.id}: Matched ad '{lead.facebook_ad_name}' → {meta_ad.ad_id}")
        
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
