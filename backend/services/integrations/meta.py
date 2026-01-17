from config import settings
import logging
import time
import requests
import json

logger = logging.getLogger(__name__)

# Try to import facebook_business, make it optional
# Note: Server-side events API might not be available in all versions
FACEBOOK_BUSINESS_AVAILABLE = False
try:
    # Try the newer path first (adobjects)
    try:
        from facebook_business.adobjects.server_side.event import Event
        from facebook_business.adobjects.server_side.custom_data import CustomData
        from facebook_business.adobjects.server_side.user_data import UserData
        from facebook_business.adobjects.server_side.event_request import EventRequest
        from facebook_business.api import FacebookAdsApi
        FACEBOOK_BUSINESS_AVAILABLE = True
    except ImportError:
        # Try the older path (ad_objects with underscore)
        try:
            from facebook_business.ad_objects.server_side.event import Event
            from facebook_business.ad_objects.server_side.custom_data import CustomData
            from facebook_business.ad_objects.server_side.user_data import UserData
            from facebook_business.ad_objects.server_side.event_request import EventRequest
            from facebook_business.api import FacebookAdsApi
            FACEBOOK_BUSINESS_AVAILABLE = True
        except ImportError:
            # Server-side events not available, but this is OK - only log at debug level
            logger.debug("facebook_business server-side events not available. Meta CAPI service will be disabled.")
except Exception as e:
    logger.debug(f"Error importing facebook_business server-side modules: {e}. Meta CAPI service will be disabled.")

class MetaService:
    def __init__(self, access_token: str = None, pixel_id: str = None, dataset_id: str = None):
        """
        Inizializza il servizio Meta CAPI.
        
        Args:
            access_token: Token di accesso Meta (opzionale, usa settings se None)
            pixel_id: Pixel ID Meta (opzionale, usa settings se None) - usato come fallback se dataset_id non fornito
            dataset_id: Dataset ID Meta (opzionale) - se fornito, gli eventi vengono inviati a questo dataset
        """
        self.access_token = access_token or settings.META_ACCESS_TOKEN
        self.pixel_id = pixel_id or settings.META_PIXEL_ID
        self.dataset_id = dataset_id  # Dataset ID specifico per questa istanza
        
        if not FACEBOOK_BUSINESS_AVAILABLE:
            logger.debug("facebook_business server-side events not available. Meta CAPI service disabled.")
            return
        
        if self.access_token:
            FacebookAdsApi.init(access_token=self.access_token)
        else:
            logger.warning("META_ACCESS_TOKEN not set. Meta service disabled.")

    def _is_hash(self, value: str) -> bool:
        """
        Verifica se un valore è un hash SHA256 (64 caratteri esadecimali).
        
        Args:
            value: Valore da verificare
            
        Returns:
            True se sembra un hash SHA256, False altrimenti
        """
        if not value:
            return False
        # Hash SHA256 è sempre 64 caratteri esadecimali
        return len(value) == 64 and all(c in '0123456789abcdef' for c in value.lower())

    def send_custom_event(
        self, 
        event_name: str, 
        lead_data: dict, 
        additional_data: dict = None,
        adset_id: str = None,
        campaign_id: str = None,
        ad_id: str = None
    ):
        """
        Sends a Custom Event to Meta CAPI.
        
        Args:
            event_name: Nome dell'evento custom
            lead_data: Dati lead (email, phone, province)
                       NOTA: email e phone sono già hash SHA256 secondo specifiche Meta
            additional_data: Dati aggiuntivi per custom_data
            adset_id: Meta AdSet ID per attribuzione corretta (opzionale, per metriche marketing)
            campaign_id: Meta Campaign ID per attribuzione corretta (opzionale, per metriche marketing)
            ad_id: Meta Ad ID per attribuzione corretta (opzionale, per metriche marketing)
        
        Note: Gli eventi vengono inviati al dataset_id se specificato, altrimenti al pixel_id.
        Il dataset è separato dal circuito campagna-adset-creatività (che sono per metriche marketing).
        
        Se email e phone sono già hash, usa l'API Graph direttamente per evitare doppio hashing.
        """
        if not FACEBOOK_BUSINESS_AVAILABLE:
            logger.debug("Skipping Meta event (facebook_business server-side events not available)")
            return None
        
        # Usa dataset_id se disponibile, altrimenti pixel_id
        target_id = self.dataset_id or self.pixel_id
        
        if not self.access_token or not target_id:
            logger.info("Skipping Meta event (creds missing: access_token or dataset_id/pixel_id)")
            return None

        try:
            # Verifica se email e phone sono già hash
            email = lead_data.get('email', '')
            phone = lead_data.get('phone', '')
            email_is_hash = self._is_hash(email)
            phone_is_hash = self._is_hash(phone)
            
            # Se abbiamo hash pre-hashed, usa API Graph direttamente
            if email_is_hash or phone_is_hash:
                return self._send_event_via_graph_api(
                    event_name=event_name,
                    lead_data=lead_data,
                    additional_data=additional_data,
                    adset_id=adset_id,
                    campaign_id=campaign_id,
                    ad_id=ad_id,
                    target_id=target_id
                )
            
            # Altrimenti usa la SDK (per retrocompatibilità, anche se non dovremmo più arrivare qui)
            user_data = UserData(
                emails=[email] if email else [],
                phones=[phone] if phone else [],
                state=lead_data.get('province') # Mapping province to state/region
            )

            # Aggiungi adset_id, campaign_id, ad_id ai custom_data per attribuzione corretta (opzionale, per metriche)
            custom_properties = additional_data or {}
            if adset_id:
                custom_properties['adset_id'] = adset_id
            if campaign_id:
                custom_properties['campaign_id'] = campaign_id
            if ad_id:
                custom_properties['ad_id'] = ad_id

            custom_data = CustomData(
                custom_properties=custom_properties
            )

            event = Event(
                event_name=event_name,
                event_time=int(time.time()),
                user_data=user_data,
                custom_data=custom_data,
                action_source="system_generated" 
            )

            events = [event]

            event_request = EventRequest(
                events=events,
                pixel_id=target_id
            )

            event_response = event_request.execute()
            logger.info(f"Meta event {event_name} sent to {'dataset' if self.dataset_id else 'pixel'} {target_id} (campaign_id={campaign_id}): {event_response}")
            return event_response

        except Exception as e:
            logger.error(f"Failed to send Meta event: {e}")
            return None

    def _send_event_via_graph_api(
        self,
        event_name: str,
        lead_data: dict,
        additional_data: dict = None,
        adset_id: str = None,
        campaign_id: str = None,
        ad_id: str = None,
        target_id: str = None
    ):
        """
        Invia evento a Meta usando Graph API direttamente, supportando hash pre-hashed.
        
        Args:
            event_name: Nome dell'evento
            lead_data: Dati lead (email e phone sono hash SHA256)
            additional_data: Dati aggiuntivi
            adset_id: Meta AdSet ID
            campaign_id: Meta Campaign ID
            ad_id: Meta Ad ID
            target_id: Pixel ID o Dataset ID
            
        Returns:
            Risposta dell'API o None in caso di errore
        """
        try:
            # Costruisci user_data con hash direttamente
            user_data = {}
            
            email = lead_data.get('email', '')
            phone = lead_data.get('phone', '')
            
            if email:
                user_data['em'] = [email]  # Hash SHA256 già pronto
            if phone:
                user_data['ph'] = [phone]  # Hash SHA256 già pronto
            
            # first_name e last_name non li usiamo (abbiamo facebook_id)
            # state/province se necessario
            if lead_data.get('province'):
                user_data['st'] = lead_data.get('province').lower()[:2] if len(lead_data.get('province', '')) >= 2 else lead_data.get('province').lower()
            
            # Costruisci custom_data
            custom_data = additional_data or {}
            if adset_id:
                custom_data['adset_id'] = adset_id
            if campaign_id:
                custom_data['campaign_id'] = campaign_id
            if ad_id:
                custom_data['ad_id'] = ad_id
            
            # Costruisci evento
            event = {
                "event_name": event_name,
                "event_time": int(time.time()),
                "user_data": user_data,
                "custom_data": custom_data,
                "action_source": "system_generated"
            }
            
            # URL Graph API per Conversions API
            url = f"https://graph.facebook.com/v18.0/{target_id}/events"
            
            payload = {
                "data": [event],
                "access_token": self.access_token
            }
            
            response = requests.post(url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"Meta event {event_name} sent via Graph API to {target_id} (campaign_id={campaign_id}): {result}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to send Meta event via Graph API: {e}")
            return None
