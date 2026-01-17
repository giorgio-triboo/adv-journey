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
import traceback
from typing import List, Dict, Optional
from datetime import datetime, timedelta, date

logger = logging.getLogger('services.integrations.meta_marketing')

# Rate limiting: delay tra chiamate API (in secondi)
API_CALL_DELAY = 2.0  # 2 secondi tra chiamate per evitare rate limit (aumentato per ridurre errori)
MAX_RETRIES = 3  # Numero massimo di retry per errori di rate limit
RETRY_BACKOFF_BASE = 10  # Base per backoff esponenziale (10, 100, 1000 secondi) - aumentato per essere più conservativi

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
    
    def _make_api_call_with_retry(self, api_call_func, *args, **kwargs):
        """
        Esegue una chiamata API con retry automatico in caso di rate limit.
        
        Args:
            api_call_func: Funzione che esegue la chiamata API
            *args, **kwargs: Argomenti da passare alla funzione
        
        Returns:
            Risultato della chiamata API
        """
        last_exception = None
        
        for attempt in range(MAX_RETRIES):
            try:
                # Delay prima della chiamata (eccetto il primo tentativo)
                if attempt > 0:
                    backoff_time = RETRY_BACKOFF_BASE ** attempt
                    logger.warning(f"[RATE LIMIT] Retry {attempt}/{MAX_RETRIES} dopo {backoff_time} secondi...")
                    time.sleep(backoff_time)
                
                result = api_call_func(*args, **kwargs)
                
                # Delay dopo chiamata riuscita per rate limiting
                time.sleep(API_CALL_DELAY)
                
                return result
                
            except Exception as e:
                last_exception = e
                error_str = str(e)
                
                # Log completo dell'errore
                logger.error(f"[API ERROR] Errore durante chiamata API (tentativo {attempt + 1}/{MAX_RETRIES}): {error_str}")
                if hasattr(e, 'api_error_code'):
                    logger.error(f"[API ERROR] Codice errore: {e.api_error_code}")
                if hasattr(e, 'api_error_subcode'):
                    logger.error(f"[API ERROR] Subcodice errore: {e.api_error_subcode}")
                if hasattr(e, 'api_error_type'):
                    logger.error(f"[API ERROR] Tipo errore: {e.api_error_type}")
                if hasattr(e, 'api_error_message'):
                    logger.error(f"[API ERROR] Messaggio errore: {e.api_error_message}")
                
                # Verifica se è un errore di rate limit
                # Controlla anche l'oggetto exception per errori strutturati di Facebook
                is_rate_limit = False
                
                # Controlla stringa errore
                if any(term in error_str.lower() for term in ['rate limit', 'request limit', 'too many', 'user request limit', 'troppe chiamate']):
                    is_rate_limit = True
                    logger.warning(f"[RATE LIMIT] Rate limit rilevato dalla stringa errore")
                
                # Controlla codice errore 17 (rate limit)
                if '17' in error_str or (hasattr(e, 'api_error_code') and e.api_error_code == 17):
                    is_rate_limit = True
                    logger.warning(f"[RATE LIMIT] Rate limit rilevato dal codice errore 17")
                
                # Controlla error_subcode 2446079 (rate limit specifico)
                if hasattr(e, 'api_error_subcode') and e.api_error_subcode == 2446079:
                    is_rate_limit = True
                    logger.warning(f"[RATE LIMIT] Rate limit rilevato dal subcodice 2446079")
                
                # Controlla tipo OAuthException con codice 17
                if hasattr(e, 'api_error_type') and e.api_error_type == 'OAuthException':
                    if hasattr(e, 'api_error_code') and e.api_error_code == 17:
                        is_rate_limit = True
                        logger.warning(f"[RATE LIMIT] Rate limit rilevato da OAuthException con codice 17")
                
                if is_rate_limit and attempt < MAX_RETRIES - 1:
                    backoff_time = RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning(f"[RATE LIMIT] Rate limit rilevato (tentativo {attempt + 1}/{MAX_RETRIES}). Attendo {backoff_time} secondi prima del retry...")
                    continue
                else:
                    # Se non è rate limit o abbiamo esaurito i retry, rilanciamo l'eccezione
                    if is_rate_limit:
                        logger.error(f"[RATE LIMIT] Rate limit persistente dopo {MAX_RETRIES} tentativi. Interrompo la sincronizzazione.")
                    else:
                        logger.error(f"[API ERROR] Errore non recuperabile dopo {MAX_RETRIES} tentativi. Interrompo la sincronizzazione.")
                    raise
        
        # Se arriviamo qui, abbiamo esaurito i retry
        raise last_exception

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

    def get_datasets(self, account_id: str = None) -> List[Dict]:
        """
        Recupera lista di dataset (pixel) disponibili.
        I dataset sono associati ai pixel e possono essere recuperati tramite account o business.
        
        Args:
            account_id: Meta account ID (opzionale, senza prefisso 'act_')
        
        Returns: List of dataset dicts with id, name
        """
        if not self.access_token:
            return []
        
        try:
            from facebook_business.adobjects.user import User
            from facebook_business.adobjects.business import Business
            
            result = []
            
            # Prova a recuperare i pixel/dataset dal business associato all'utente
            try:
                me = User(f"me")
                # Recupera i business dell'utente
                businesses = me.get_businesses(fields=['id', 'name'])
                
                for business in businesses:
                    try:
                        business_obj = Business(business.get('id'))
                        # Recupera i pixel/dataset associati al business
                        pixels = self._make_api_call_with_retry(
                            lambda: list(business_obj.get_owned_pixels(fields=['id', 'name', 'is_created_by_business']))
                        )
                        
                        for pixel in pixels:
                            result.append({
                                "dataset_id": pixel.get('id'),
                                "name": pixel.get('name', f"Pixel {pixel.get('id', 'Unknown')}"),
                                "business_id": business.get('id'),
                                "business_name": business.get('name', 'Unknown')
                            })
                    except Exception as e:
                        logger.debug(f"Error fetching pixels for business {business.get('id')}: {e}")
                        continue
            except Exception as e:
                logger.debug(f"Error fetching businesses: {e}")
            
            # Nota: I pixel/dataset sono associati al business, non direttamente all'account.
            # Se viene passato un account_id, i pixel recuperati dal business saranno comunque
            # disponibili per tutti gli account associati a quel business.
            # Non è possibile recuperare i pixel direttamente da un AdAccount.
            
            # Rimuovi duplicati basati su dataset_id
            seen = set()
            unique_result = []
            for item in result:
                dataset_id = item.get('dataset_id')
                if dataset_id and dataset_id not in seen:
                    seen.add(dataset_id)
                    unique_result.append(item)
            
            return unique_result
        except Exception as e:
            logger.error(f"Error fetching Meta datasets: {e}")
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
            # Usa rate limiting con retry
            campaigns = self._make_api_call_with_retry(
                lambda: list(account.get_campaigns(fields=fields))
            )
            
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
                
                # Apply filters - name_pattern è sempre obbligatorio
                if not filters or 'name_pattern' not in filters:
                    logger.warning(f"[SYNC] Filtro name_pattern mancante, saltando campagna {camp_data['campaign_id']}")
                    continue
                
                # Filter by name pattern (obbligatorio) - verifica se il nome contiene il pattern
                pattern = filters['name_pattern'].lower()
                campaign_name_lower = camp_data['name'].lower()
                
                # Verifica se il pattern è contenuto nel nome (case-insensitive)
                if pattern not in campaign_name_lower:
                    logger.debug(f"[SYNC] Campagna '{camp_data['name']}' non contiene pattern '{pattern}', saltata")
                    continue
                
                logger.debug(f"[SYNC] Campagna '{camp_data['name']}' contiene pattern '{pattern}', inclusa")
                
                # Filter by status (opzionale)
                if 'status' in filters and filters['status']:
                    status_list = filters['status'] if isinstance(filters['status'], list) else [filters['status']]
                    if camp_data['status'] not in status_list:
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
            # Usa rate limiting con retry
            adsets = self._make_api_call_with_retry(
                lambda: list(campaign.get_ad_sets(fields=['id', 'name', 'status', 'optimization_goal', 'targeting']))
            )
            
            result = []
            for adset in adsets:
                # Convert targeting object to dict if it's not already a dict
                targeting = adset.get('targeting', {})
                if targeting and not isinstance(targeting, dict):
                    # If it's a Targeting object, convert to dict
                    try:
                        if hasattr(targeting, 'export_all_data'):
                            targeting = targeting.export_all_data()
                        elif hasattr(targeting, '__dict__'):
                            targeting = dict(targeting.__dict__)
                        else:
                            # Try to convert using dict() constructor
                            targeting = dict(targeting) if targeting else {}
                    except Exception as e:
                        logger.warning(f"Error converting targeting to dict: {e}, using empty dict")
                        targeting = {}
                
                result.append({
                    "adset_id": adset.get('id'),
                    "name": adset.get('name', ''),
                    "status": adset.get('status', 'UNKNOWN'),
                    "optimization_goal": adset.get('optimization_goal', ''),
                    "targeting": targeting if isinstance(targeting, dict) else {}
                })
            
            return result
        except Exception as e:
            logger.error(f"Error fetching adsets for campaign {campaign_id}: {e}")
            return []

    def get_ads(self, adset_id: str) -> List[Dict]:
        """
        Recupera ads (creatività) per un adset.
        Include thumbnail_url dell'immagine della creatività.
        """
        if not self.access_token:
            return []
        
        try:
            adset = AdSet(adset_id)
            # Richiedi i campi necessari incluso creative con thumbnail_url
            ads = self._make_api_call_with_retry(
                lambda: list(adset.get_ads(fields=['id', 'name', 'status', 'creative{id,thumbnail_url,image_url,object_story_spec}']))
            )
            
            result = []
            for ad in ads:
                creative = ad.get('creative', {})
                
                # Prova a ottenere thumbnail_url da diverse fonti
                thumbnail_url = ''
                if creative:
                    # 1. Prova thumbnail_url diretto
                    thumbnail_url = creative.get('thumbnail_url', '')
                    
                    # 2. Se non c'è, prova image_url
                    if not thumbnail_url:
                        thumbnail_url = creative.get('image_url', '')
                    
                    # 3. Se ancora non c'è, prova a estrarre da object_story_spec
                    if not thumbnail_url:
                        object_story_spec = creative.get('object_story_spec', {})
                        if object_story_spec:
                            # Per link ads, l'immagine può essere in link_data
                            link_data = object_story_spec.get('link_data', {})
                            if link_data:
                                thumbnail_url = link_data.get('image_url', '') or link_data.get('picture', '')
                            
                            # Per photo ads, l'immagine può essere in photo_data
                            photo_data = object_story_spec.get('photo_data', {})
                            if not thumbnail_url and photo_data:
                                thumbnail_url = photo_data.get('image_url', '')
                
                result.append({
                    "ad_id": ad.get('id'),
                    "name": ad.get('name', ''),
                    "status": ad.get('status', 'UNKNOWN'),
                    "creative_id": creative.get('id', '') if creative else '',
                    "creative_thumbnail_url": thumbnail_url
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
        
        # Aggiungi sempre ad_id, campaign_id, adset_id ai fields se level='ad'
        # perché sono necessari per associare i dati agli ads nel database
        if level == 'ad':
            required_fields = ['ad_id', 'campaign_id', 'adset_id', 'date_start']
            for field in required_fields:
                if field not in fields:
                    fields.append(field)
        
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
            
            logger.info(f"Retrieved {len(insights)} insights from Meta API for account {account_id}")
            if insights and len(insights) > 0:
                # Log first insight to see structure
                first_insight = insights[0]
                logger.info(f"Sample insight structure - Keys: {list(first_insight.keys())}")
                logger.info(f"Sample insight - ad_id: {first_insight.get('ad_id')}, ad_id type: {type(first_insight.get('ad_id'))}, date: {first_insight.get('date_start')}, campaign_id: {first_insight.get('campaign_id')}")
                # Log raw insight dict to see all fields
                logger.debug(f"Raw first insight: {dict(first_insight)}")
            
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
                
                # Extract ad_id - potrebbe essere in formato "act_123456/ad_789" o solo "789"
                # L'API Meta potrebbe restituire ad_id come oggetto o come stringa
                raw_ad_id = insight.get('ad_id', '')
                
                # Se ad_id è un oggetto (dict), prova a estrarre l'id
                if isinstance(raw_ad_id, dict):
                    raw_ad_id = raw_ad_id.get('id', raw_ad_id.get('value', ''))
                
                # Converti a stringa se necessario
                if raw_ad_id:
                    raw_ad_id = str(raw_ad_id)
                
                ad_id_clean = raw_ad_id
                if raw_ad_id and '/' in raw_ad_id:
                    # Se è in formato "act_123456/ad_789", estrai solo "789"
                    ad_id_clean = raw_ad_id.split('/')[-1].replace('ad_', '')
                
                # Rimuovi eventuali prefissi
                if ad_id_clean and ad_id_clean.startswith('act_'):
                    parts = ad_id_clean.split('/')
                    if len(parts) > 1:
                        ad_id_clean = parts[-1].replace('ad_', '')
                
                result.append({
                    "date": insight.get('date_start', ''),
                    "campaign_id": insight.get('campaign_id', ''),
                    "adset_id": insight.get('adset_id', ''),
                    "ad_id": ad_id_clean,  # Usa la versione pulita
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
        
        logger.info(f"[SYNC] ========== INIZIO SINCRONIZZAZIONE CAMPAIGNE PER ACCOUNT {account_id} ==========")
        logger.info(f"[SYNC] Filtri applicati: {filters}")
        
        # Get or create account
        account_record = db_session.query(MetaAccount).filter(
            MetaAccount.account_id == account_id
        ).first()
        
        if not account_record:
            logger.info(f"[SYNC] Account {account_id} non trovato nel DB, creazione nuovo record...")
            # Test connection first
            test_result = self.test_connection(account_id)
            if not test_result['success']:
                logger.error(f"[SYNC] Errore connessione account {account_id}: {test_result['message']}")
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
            logger.info(f"[SYNC] Account {account_id} creato: {account_record.name}")
        else:
            logger.info(f"[SYNC] Account {account_id} trovato: {account_record.name} (ID DB: {account_record.id})")
        
        # Get campaigns - i filtri sono sempre obbligatori
        if not filters or not filters.get('name_pattern'):
            logger.warning(
                f"[SYNC] Account {account_id}: filtri obbligatori mancanti (name_pattern richiesto). "
                f"Sync saltata per questo account. Configura i filtri via UI prima di abilitare la sync automatica."
            )
            # Non sollevare eccezione, ma loggare un warning e saltare la sync
            return {
                "campaigns_created": 0,
                "campaigns_updated": 0,
                "skipped": True,
                "reason": "Filtri obbligatori mancanti: name_pattern è richiesto"
            }
        
        logger.info(f"[SYNC] Recupero campagne da Meta API per account {account_id} con filtri: {filters}")
        try:
            campaigns = self.get_campaigns(account_id, filters=filters)
            logger.info(f"[SYNC] Trovate {len(campaigns)} campagne da Meta API (dopo filtri: {filters})")
            if campaigns:
                logger.info(f"[SYNC] Prime 5 campagne trovate: {[c['name'] for c in campaigns[:5]]}")
        except Exception as e:
            error_traceback = traceback.format_exc()
            logger.error(f"[SYNC] Errore durante recupero campagne per account {account_id}: {e}")
            logger.error(f"[SYNC] Traceback completo: {error_traceback}")
            raise
        
        campaigns_created = 0
        campaigns_updated = 0
        
        for idx, camp_data in enumerate(campaigns, 1):
            logger.info(f"[SYNC] Elaborazione campagna {idx}/{len(campaigns)}: {camp_data['campaign_id']} - {camp_data['name']}")
            
            try:
                # Get or create campaign
                campaign_record = db_session.query(MetaCampaign).filter(
                    MetaCampaign.campaign_id == camp_data['campaign_id']
                ).first()
                
                if not campaign_record:
                    logger.info(f"[SYNC] Creazione nuova campagna: {camp_data['campaign_id']} - {camp_data['name']}")
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
                    campaigns_created += 1
                    # Commit immediato per salvare la campagna
                    try:
                        db_session.commit()
                        logger.debug(f"[SYNC] Campagna {camp_data['campaign_id']} salvata nel database")
                    except Exception as commit_err:
                        error_traceback = traceback.format_exc()
                        logger.error(f"[SYNC] Errore durante commit campagna {camp_data['campaign_id']}: {commit_err}")
                        logger.error(f"[SYNC] Traceback: {error_traceback}")
                        db_session.rollback()
                        raise
                else:
                    logger.debug(f"[SYNC] Aggiornamento campagna esistente: {camp_data['campaign_id']}")
                    # Update existing
                    campaign_record.name = camp_data['name']
                    campaign_record.status = camp_data['status']
                    campaign_record.updated_at = datetime.utcnow()
                    campaigns_updated += 1
                    # Commit immediato per salvare l'aggiornamento
                    try:
                        db_session.commit()
                        logger.debug(f"[SYNC] Campagna {camp_data['campaign_id']} aggiornata nel database")
                    except Exception as commit_err:
                        error_traceback = traceback.format_exc()
                        logger.error(f"[SYNC] Errore durante commit aggiornamento campagna {camp_data['campaign_id']}: {commit_err}")
                        logger.error(f"[SYNC] Traceback: {error_traceback}")
                        db_session.rollback()
                        raise
            except Exception as camp_err:
                error_traceback = traceback.format_exc()
                logger.error(f"[SYNC] Errore durante elaborazione campagna {camp_data['campaign_id']}: {camp_err}")
                logger.error(f"[SYNC] Traceback: {error_traceback}")
                db_session.rollback()
                # Continua con la prossima campagna invece di interrompere tutto
                continue
            
            # Get adsets con delay per rate limiting
            logger.info(f"[SYNC] Attendo {API_CALL_DELAY} secondi prima di recuperare adsets per campagna {camp_data['campaign_id']}...")
            time.sleep(API_CALL_DELAY)  # Delay aggiuntivo prima di recuperare adsets
            
            try:
                logger.info(f"[SYNC] Recupero adsets per campagna {camp_data['campaign_id']} ({camp_data['name']})...")
                adsets = self.get_adsets(camp_data['campaign_id'])
                logger.info(f"[SYNC] Trovati {len(adsets)} adsets per campagna {camp_data['campaign_id']}")
            except Exception as e:
                error_traceback = traceback.format_exc()
                logger.error(f"[SYNC] Errore recupero adsets per campagna {camp_data['campaign_id']} ({camp_data['name']}): {e}")
                logger.error(f"[SYNC] Traceback completo: {error_traceback}")
                adsets = []  # Continua anche se fallisce
            
            campaign_adsets_created = 0
            campaign_adsets_updated = 0
            
            for adset_data in adsets:
                adset_record = db_session.query(MetaAdSet).filter(
                    MetaAdSet.adset_id == adset_data['adset_id']
                ).first()
                
                if not adset_record:
                    logger.debug(f"[SYNC] Creazione nuovo adset: {adset_data['adset_id']} - {adset_data['name']}")
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
                    campaign_adsets_created += 1
                    # Commit immediato per salvare l'adset
                    try:
                        db_session.commit()
                    except Exception as commit_err:
                        logger.error(f"[SYNC] Errore durante commit adset {adset_data['adset_id']}: {commit_err}")
                        db_session.rollback()
                        continue
                else:
                    logger.debug(f"[SYNC] Aggiornamento adset esistente: {adset_data['adset_id']}")
                    adset_record.name = adset_data['name']
                    adset_record.status = adset_data['status']
                    adset_record.updated_at = datetime.utcnow()
                    campaign_adsets_updated += 1
                    # Commit immediato per salvare l'aggiornamento
                    try:
                        db_session.commit()
                    except Exception as commit_err:
                        logger.error(f"[SYNC] Errore durante commit aggiornamento adset {adset_data['adset_id']}: {commit_err}")
                        db_session.rollback()
                        continue
                
                # Get ads con delay per rate limiting
                logger.info(f"[SYNC] Attendo {API_CALL_DELAY} secondi prima di recuperare ads per adset {adset_data['adset_id']}...")
                time.sleep(API_CALL_DELAY)  # Delay aggiuntivo prima di recuperare ads
                
                try:
                    logger.info(f"[SYNC] Recupero ads per adset {adset_data['adset_id']} ({adset_data['name']})...")
                    ads = self.get_ads(adset_data['adset_id'])
                    logger.info(f"[SYNC] Trovati {len(ads)} ads per adset {adset_data['adset_id']}")
                except Exception as e:
                    error_traceback = traceback.format_exc()
                    logger.error(f"[SYNC] Errore recupero ads per adset {adset_data['adset_id']} ({adset_data['name']}): {e}")
                    logger.error(f"[SYNC] Traceback completo: {error_traceback}")
                    ads = []  # Continua anche se fallisce
                
                ads_created = 0
                ads_updated = 0
                
                for ad_data in ads:
                    ad_record = db_session.query(MetaAd).filter(
                        MetaAd.ad_id == ad_data['ad_id']
                    ).first()
                    
                    if not ad_record:
                        logger.debug(f"[SYNC] Creazione nuovo ad: {ad_data['ad_id']} - {ad_data['name']}")
                        ad_record = MetaAd(
                            adset_id=adset_record.id,
                            ad_id=ad_data['ad_id'],
                            name=ad_data['name'],
                            status=ad_data['status'],
                            creative_id=ad_data.get('creative_id', ''),
                            creative_thumbnail_url=ad_data.get('creative_thumbnail_url', '')
                        )
                        db_session.add(ad_record)
                        ads_created += 1
                    else:
                        logger.debug(f"[SYNC] Aggiornamento ad esistente: {ad_data['ad_id']}")
                        ad_record.name = ad_data['name']
                        ad_record.status = ad_data['status']
                        # Aggiorna anche creative_thumbnail_url se disponibile
                        if ad_data.get('creative_thumbnail_url'):
                            ad_record.creative_thumbnail_url = ad_data.get('creative_thumbnail_url', '')
                        ad_record.updated_at = datetime.utcnow()
                        ads_updated += 1
                
                # Commit immediato per salvare gli ads
                try:
                    db_session.commit()
                except Exception as commit_err:
                    logger.error(f"[SYNC] Errore durante commit ads per adset {adset_data['adset_id']}: {commit_err}")
                    db_session.rollback()
                
                logger.debug(f"[SYNC] Adset {adset_data['adset_id']} completato: {ads_created} ads creati, {ads_updated} ads aggiornati")
            
            logger.debug(f"[SYNC] Campagna {camp_data['campaign_id']} completata: {campaign_adsets_created} adsets creati, {campaign_adsets_updated} adsets aggiornati")
        
        # Il commit finale non è più necessario perché abbiamo già committato ogni campagna
        # Ma facciamo un commit finale per sicurezza
        try:
            db_session.commit()
            logger.info(f"[SYNC] ========== SINCRONIZZAZIONE COMPLETATA PER ACCOUNT {account_id} ==========")
            logger.info(f"[SYNC] Riepilogo finale: {campaigns_created} campagne create, {campaigns_updated} campagne aggiornate su {len(campaigns)} totali")
            logger.info(f"[SYNC] Modifiche salvate nel database per account {account_id}")
        except Exception as e:
            error_traceback = traceback.format_exc()
            logger.error(f"[SYNC] Errore durante commit finale database per account {account_id}: {e}")
            logger.error(f"[SYNC] Traceback completo: {error_traceback}")
            db_session.rollback()
            # Non rilanciamo l'eccezione perché le campagne sono già state salvate individualmente
        
        return {
            "campaigns_created": campaigns_created,
            "campaigns_updated": campaigns_updated,
            "skipped": False
        }
