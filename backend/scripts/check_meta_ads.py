#!/usr/bin/env python3
"""
Script per verificare se ci sono ads nel database per le campagne Meta.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import MetaAccount, MetaCampaign, MetaAd, MetaAdSet

def check_ads():
    db = SessionLocal()
    
    try:
        account_id = '1209978493874443'
        account = db.query(MetaAccount).filter(MetaAccount.account_id == account_id).first()
        
        if not account:
            print(f"❌ Account {account_id} non trovato!")
            return
        
        print(f"\n📊 Account: {account.name} ({account.account_id})")
        
        campaigns = db.query(MetaCampaign).filter(MetaCampaign.account_id == account.id).all()
        print(f"📈 Campagne trovate: {len(campaigns)}")
        
        total_ads = 0
        for campaign in campaigns:
            adsets = db.query(MetaAdSet).filter(MetaAdSet.campaign_id == campaign.id).all()
            campaign_ads = 0
            
            for adset in adsets:
                ads = db.query(MetaAd).filter(MetaAd.adset_id == adset.id).all()
                campaign_ads += len(ads)
                total_ads += len(ads)
                
                if len(ads) > 0:
                    print(f"\n  🎯 Campagna: {campaign.name}")
                    print(f"     AdSet: {adset.name}")
                    print(f"     Ads: {len(ads)}")
                    print(f"     Ad IDs: {[ad.ad_id for ad in ads[:5]]}")
        
        print(f"\n✅ Totale ads nel database: {total_ads}")
        
        if total_ads == 0:
            print("⚠️  PROBLEMA: Non ci sono ads nel database!")
            print("   La sincronizzazione delle campagne potrebbe non aver salvato gli ads.")
        
    except Exception as e:
        print(f"❌ Errore: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_ads()
