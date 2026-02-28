#!/usr/bin/env python3
"""
Script per verificare se i dati Meta Marketing sono stati salvati nel database.
"""
import sys
import os

# Aggiungi il path del backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import MetaAccount, MetaCampaign, MetaAd, MetaMarketingData
from datetime import datetime, date
from sqlalchemy import func

def check_marketing_data():
    db = SessionLocal()
    
    try:
        # Conta totale record
        total_records = db.query(MetaMarketingData).count()
        print(f"\n📊 TOTALE RECORD MetaMarketingData: {total_records}")
        
        if total_records == 0:
            print("❌ Nessun dato salvato nel database!")
            return
        
        # Conta per account
        print("\n📈 Dati per Account:")
        accounts = db.query(MetaAccount).filter(MetaAccount.is_active == True).all()
        for account in accounts:
            count = db.query(MetaMarketingData).join(MetaAd).join(MetaAdSet).join(MetaCampaign).filter(
                MetaCampaign.account_id == account.id
            ).count()
            if count > 0:
                print(f"  - {account.name} ({account.account_id}): {count} record")
        
        # Conta per data (ultimi 7 giorni)
        print("\n📅 Dati per Data (ultimi 7 giorni):")
        today = date.today()
        for i in range(7):
            check_date = today - timedelta(days=i)
            count = db.query(MetaMarketingData).filter(
                func.date(MetaMarketingData.date) == check_date
            ).count()
            if count > 0:
                print(f"  - {check_date}: {count} record")
        
        # Conta per campagna
        print("\n🎯 Dati per Campagna (top 10):")
        campaigns = db.query(MetaCampaign).join(MetaAccount).filter(
            MetaAccount.is_active == True
        ).limit(10).all()
        
        for campaign in campaigns:
            count = db.query(MetaMarketingData).join(MetaAd).join(MetaAdSet).filter(
                MetaAdSet.campaign_id == campaign.id
            ).count()
            if count > 0:
                print(f"  - {campaign.name}: {count} record")
        
        # Verifica dati per la data specifica della sync (2026-01-15)
        sync_date = date(2026, 1, 15)
        print(f"\n🔍 Verifica dati per data sync: {sync_date}")
        records_for_date = db.query(MetaMarketingData).filter(
            func.date(MetaMarketingData.date) == sync_date
        ).all()
        
        print(f"  Trovati {len(records_for_date)} record per {sync_date}")
        
        if records_for_date:
            print("\n  Esempi di record salvati:")
            for i, record in enumerate(records_for_date[:5]):
                ad = db.query(MetaAd).filter(MetaAd.id == record.ad_id).first()
                if ad:
                    print(f"    {i+1}. Ad ID: {ad.ad_id}, Date: {record.date}, Spend: {record.spend}, "
                          f"Impressions: {record.impressions}, Clicks: {record.clicks}, Conversions: {record.conversions}")
        else:
            print("  ⚠️  Nessun record trovato per questa data!")
            
            # Verifica se ci sono ads per le campagne sincronizzate
            print("\n  Verifica ads disponibili:")
            campaigns = db.query(MetaCampaign).join(MetaAccount).filter(
                MetaAccount.account_id == '1209978493874443'
            ).all()
            
            for campaign in campaigns:
                ads = db.query(MetaAd).join(MetaAdSet).filter(
                    MetaAdSet.campaign_id == campaign.id
                ).count()
                print(f"    - {campaign.name}: {ads} ads")
        
    except Exception as e:
        print(f"❌ Errore: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    from datetime import timedelta
    from models import MetaAdSet
    check_marketing_data()
