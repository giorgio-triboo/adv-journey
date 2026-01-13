"""
Service per l'ingestion di dati marketing da Meta Graph API.
Gestisce account, campagne, adset, ads e metriche.
"""
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.adobjects.ad import Ad
from facebook_business.adobjects.adsinsights import AdsInsights
from config import settings
import logging
import time
from typing import List, Dict, Optional
from datetime import datetime, timedelta, date

logger = logging.getLogger(__name__)

class MetaMarketingService:
    def __init__(self, access_token: Optional[str] = None):
        """
        Inizializza il service Meta Marketing.
        Se access_token non fornito, usa quello di default da settings.
        """
        self.access_token = access_token or settings.META_ACCESS_TOKEN
        if self.access_token:
            FacebookAdsApi.init(access_token=self.access_token)
        else:
            logger.warning("META_ACCESS_TOKEN not set. Meta Marketing service disabled.")

    def test_connection(self, account_id: str) -> Dict:
        """
        Testa la connessione a un account Meta.
        Returns: {"success": bool, "message": str, "account_name": str}
        """
        if not self.access_token:
            return {"success": False, "message": "Token di accesso non configurato"}
        
        try:
            account = AdAccount(f"act_{account_id}")
            account_info = account.api_get(fields=['name', 'account_id', 'currency'])
            return {
                "success": True,
                "message": "Connessione riuscita",
                "account_name": account_info.get('name', 'Sconosciuto'),
                "account_id": account_info.get('account_id'),
                "currency": account_info.get('currency', 'EUR')
            }
        except Exception as e:
            logger.error(f"Meta connection test failed: {e}")
            # Traduci errori comuni
            error_msg = str(e)
            if "Permissions" in error_msg or "permissions" in error_msg.lower():
                error_msg = "Errore di permessi"
            elif "Invalid" in error_msg or "invalid" in error_msg.lower():
                error_msg = "Token o account non valido"
            elif "expired" in error_msg.lower():
                error_msg = "Token scaduto"
            return {"success": False, "message": error_msg}

    def get_accounts(self) -> List[Dict]:
        """
        Recupera lista di tutti gli account disponibili per il token.
        Returns: List of account dicts with id, name, currency
        """
        if not self.access_token:
            return []
        
        try:
            # Get user's ad accounts
            from facebook_business.adobjects.user import User
            me = User(f"me")
            accounts = me.get_ad_accounts(fields=['name', 'account_id', 'currency', 'timezone_name'])
            
            result = []
            for account in accounts:
                result.append({
                    "account_id": account.get('account_id', '').replace('act_', ''),
                    "name": account.get('name', 'Unknown'),
                    "currency": account.get('currency', 'EUR'),
                    "timezone": account.get('timezone_name', 'UTC')
                })
            
            return result
        except Exception as e:
            logger.error(f"Error fetching Meta accounts: {e}")
            return []

    def get_campaigns(
        self, 
        account_id: str, 
        fields: Optional[List[str]] = None,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Recupera campagne da un account Meta.
        
        Args:
            account_id: Meta account ID (senza prefisso 'act_')
            fields: Campi da recuperare (default: id, name, status, objective, daily_budget, lifetime_budget)
            filters: Filtri da applicare:
                - tag: Lista di tag da filtrare
                - name_pattern: Pattern per nome (es. "contains", "starts_with")
                - status: Lista di stati (ACTIVE, PAUSED, etc.)
        
        Returns: Lista di campagne
        """
        if not self.access_token:
            return []
        
        if fields is None:
            fields = ['id', 'name', 'status', 'objective', 'daily_budget', 'lifetime_budget', 'created_time']
        
        try:
            account = AdAccount(f"act_{account_id}")
            campaigns = account.get_campaigns(fields=fields)
            
            result = []
            for campaign in campaigns:
                camp_data = {
                    "campaign_id": campaign.get('id'),
                    "name": campaign.get('name', ''),
                    "status": campaign.get('status', 'UNKNOWN'),
                    "objective": campaign.get('objective', ''),
                    "daily_budget": campaign.get('daily_budget', '0'),
                    "lifetime_budget": campaign.get('lifetime_budget', '0'),
                    "created_time": campaign.get('created_time', '')
                }
                
                # Apply filters
                if filters:
                    # Filter by tag (if tags field is requested)
                    if 'tag' in filters and filters['tag']:
                        # Note: Tags need to be fetched separately or included in fields
                        # For now, we'll fetch tags if needed
                        pass
                    
                    # Filter by name pattern
                    if 'name_pattern' in filters:
                        pattern = filters['name_pattern'].lower()
                        if pattern not in camp_data['name'].lower():
                            continue
                    
                    # Filter by status
                    if 'status' in filters:
                        if camp_data['status'] not in filters['status']:
                            continue
                
                result.append(camp_data)
            
            return result
        except Exception as e:
            logger.error(f"Error fetching campaigns for account {account_id}: {e}")
            return []

    def get_campaign_tags(self, account_id: str, campaign_id: str) -> List[str]:
        """
        Recupera i tag di una campagna.
        """
        if not self.access_token:
            return []
        
        try:
            campaign = Campaign(campaign_id)
            tags = campaign.api_get(fields=['name'])  # Tags might need special handling
            # Meta API might require different approach for tags
            # This is a placeholder - actual implementation depends on Meta API version
            return []
        except Exception as e:
            logger.error(f"Error fetching tags for campaign {campaign_id}: {e}")
            return []

    def get_adsets(self, campaign_id: str) -> List[Dict]:
        """
        Recupera adset per una campagna.
        """
        if not self.access_token:
            return []
        
        try:
            campaign = Campaign(campaign_id)
            adsets = campaign.get_ad_sets(fields=['id', 'name', 'status', 'optimization_goal', 'targeting'])
            
            result = []
            for adset in adsets:
                result.append({
                    "adset_id": adset.get('id'),
                    "name": adset.get('name', ''),
                    "status": adset.get('status', 'UNKNOWN'),
                    "optimization_goal": adset.get('optimization_goal', ''),
                    "targeting": adset.get('targeting', {})
                })
            
            return result
        except Exception as e:
            logger.error(f"Error fetching adsets for campaign {campaign_id}: {e}")
            return []

    def get_ads(self, adset_id: str) -> List[Dict]:
        """
        Recupera ads (creatività) per un adset.
        """
        if not self.access_token:
            return []
        
        try:
            adset = AdSet(adset_id)
            ads = adset.get_ads(fields=['id', 'name', 'status', 'creative'])
            
            result = []
            for ad in ads:
                creative = ad.get('creative', {})
                result.append({
                    "ad_id": ad.get('id'),
                    "name": ad.get('name', ''),
                    "status": ad.get('status', 'UNKNOWN'),
                    "creative_id": creative.get('id', '') if creative else '',
                    "creative_thumbnail_url": creative.get('thumbnail_url', '') if creative else ''
                })
            
            return result
        except Exception as e:
            logger.error(f"Error fetching ads for adset {adset_id}: {e}")
            return []

    def get_insights(
        self,
        account_id: str,
        level: str = 'ad',
        date_preset: str = 'last_7d',
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        fields: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Recupera metriche marketing (insights) da Meta.
        
        Args:
            account_id: Meta account ID
            level: Livello di aggregazione (account, campaign, adset, ad)
            date_preset: Preset date (last_7d, last_30d, etc.) o None se usi start_date/end_date
            start_date: Data inizio (se None, usa date_preset)
            end_date: Data fine (se None, usa date_preset)
            fields: Campi da recuperare (default: spend, impressions, clicks, conversions, etc.)
        
        Returns: Lista di insights con metriche
        """
        if not self.access_token:
            return []
        
        if fields is None:
            fields = [
                'spend', 'impressions', 'clicks', 'ctr', 'cpc', 'cpm',
                'actions', 'action_values', 'cost_per_action_type'
            ]
        
        try:
            account = AdAccount(f"act_{account_id}")
            
            params = {
                'level': level,
                'fields': fields,
                'time_increment': 1  # Daily breakdown
            }
            
            if date_preset:
                params['date_preset'] = date_preset
            elif start_date and end_date:
                params['time_range'] = {
                    'since': start_date.strftime('%Y-%m-%d'),
                    'until': end_date.strftime('%Y-%m-%d')
                }
            
            insights = account.get_insights(params=params)
            
            result = []
            for insight in insights:
                # Parse actions for conversions
                actions = insight.get('actions', [])
                conversions = 0
                for action in actions:
                    if action.get('action_type') in ['lead', 'offsite_conversion']:
                        conversions += int(action.get('value', 0))
                
                # Calculate CTR, CPC, CPM if not provided
                spend = float(insight.get('spend', 0))
                impressions = int(insight.get('impressions', 0))
                clicks = int(insight.get('clicks', 0))
                
                ctr = (clicks / impressions * 100) if impressions > 0 else 0
                cpc = (spend / clicks) if clicks > 0 else 0
                cpm = (spend / impressions * 1000) if impressions > 0 else 0
                
                result.append({
                    "date": insight.get('date_start', ''),
                    "campaign_id": insight.get('campaign_id', ''),
                    "adset_id": insight.get('adset_id', ''),
                    "ad_id": insight.get('ad_id', ''),
                    "spend": self._format_currency(spend),
                    "impressions": impressions,
                    "clicks": clicks,
                    "conversions": conversions,
                    "ctr": self._format_percentage(ctr),
                    "cpc": self._format_currency(cpc),
                    "cpm": self._format_currency(cpm),
                    "raw_data": dict(insight)
                })
            
            return result
        except Exception as e:
            logger.error(f"Error fetching insights for account {account_id}: {e}")
            return []

    def _format_currency(self, value: float) -> str:
        """Formatta valore monetario con virgola come separatore decimale."""
        return f"{value:,.2f}".replace('.', ',')

    def _format_percentage(self, value: float) -> str:
        """Formatta percentuale con virgola come separatore decimale."""
        return f"{value:.2f}".replace('.', ',')

    def sync_account_campaigns(self, account_id: str, db_session, filters: Optional[Dict] = None):
        """
        Sincronizza campagne di un account nel database.
        Crea/aggiorna record in MetaAccount, MetaCampaign, MetaAdSet, MetaAd.
        """
        from models import MetaAccount, MetaCampaign, MetaAdSet, MetaAd
        
        # Get or create account
        account_record = db_session.query(MetaAccount).filter(
            MetaAccount.account_id == account_id
        ).first()
        
        if not account_record:
            # Test connection first
            test_result = self.test_connection(account_id)
            if not test_result['success']:
                raise Exception(f"Cannot connect to account {account_id}: {test_result['message']}")
            
            # Cripta il token prima di salvarlo nel database
            from services.utils.crypto import encrypt_token
            encrypted_token = encrypt_token(self.access_token)
            
            account_record = MetaAccount(
                account_id=account_id,
                name=test_result.get('account_name', 'Unknown'),
                access_token=encrypted_token,
                is_active=True,
                sync_enabled=True
            )
            db_session.add(account_record)
            db_session.flush()
        
        # Get campaigns
        campaigns = self.get_campaigns(account_id, filters=filters)
        
        for camp_data in campaigns:
            # Get or create campaign
            campaign_record = db_session.query(MetaCampaign).filter(
                MetaCampaign.campaign_id == camp_data['campaign_id']
            ).first()
            
            if not campaign_record:
                campaign_record = MetaCampaign(
                    account_id=account_record.id,
                    campaign_id=camp_data['campaign_id'],
                    name=camp_data['name'],
                    status=camp_data['status'],
                    objective=camp_data['objective'],
                    daily_budget=camp_data.get('daily_budget', '0'),
                    lifetime_budget=camp_data.get('lifetime_budget', '0'),
                    is_synced=True
                )
                db_session.add(campaign_record)
                db_session.flush()
            else:
                # Update existing
                campaign_record.name = camp_data['name']
                campaign_record.status = camp_data['status']
                campaign_record.updated_at = datetime.utcnow()
            
            # Get adsets
            adsets = self.get_adsets(camp_data['campaign_id'])
            for adset_data in adsets:
                adset_record = db_session.query(MetaAdSet).filter(
                    MetaAdSet.adset_id == adset_data['adset_id']
                ).first()
                
                if not adset_record:
                    adset_record = MetaAdSet(
                        campaign_id=campaign_record.id,
                        adset_id=adset_data['adset_id'],
                        name=adset_data['name'],
                        status=adset_data['status'],
                        optimization_goal=adset_data['optimization_goal'],
                        targeting=adset_data.get('targeting', {})
                    )
                    db_session.add(adset_record)
                    db_session.flush()
                else:
                    adset_record.name = adset_data['name']
                    adset_record.status = adset_data['status']
                    adset_record.updated_at = datetime.utcnow()
                
                # Get ads
                ads = self.get_ads(adset_data['adset_id'])
                for ad_data in ads:
                    ad_record = db_session.query(MetaAd).filter(
                        MetaAd.ad_id == ad_data['ad_id']
                    ).first()
                    
                    if not ad_record:
                        ad_record = MetaAd(
                            adset_id=adset_record.id,
                            ad_id=ad_data['ad_id'],
                            name=ad_data['name'],
                            status=ad_data['status'],
                            creative_id=ad_data.get('creative_id', ''),
                            creative_thumbnail_url=ad_data.get('creative_thumbnail_url', '')
                        )
                        db_session.add(ad_record)
                    else:
                        ad_record.name = ad_data['name']
                        ad_record.status = ad_data['status']
                        ad_record.updated_at = datetime.utcnow()
        
        db_session.commit()
        logger.info(f"Synced {len(campaigns)} campaigns for account {account_id}")
