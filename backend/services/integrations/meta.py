from config import settings
import logging
import time

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
            lead_data: Dati lead (email, phone, first_name, last_name, province)
            additional_data: Dati aggiuntivi per custom_data
            adset_id: Meta AdSet ID per attribuzione corretta (opzionale, per metriche marketing)
            campaign_id: Meta Campaign ID per attribuzione corretta (opzionale, per metriche marketing)
            ad_id: Meta Ad ID per attribuzione corretta (opzionale, per metriche marketing)
        
        Note: Gli eventi vengono inviati al dataset_id se specificato, altrimenti al pixel_id.
        Il dataset è separato dal circuito campagna-adset-creatività (che sono per metriche marketing).
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
            user_data = UserData(
                emails=[lead_data.get('email')] if lead_data.get('email') else [],
                phones=[lead_data.get('phone')] if lead_data.get('phone') else [],
                first_name=lead_data.get('first_name'),
                last_name=lead_data.get('last_name'),
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

            # Se abbiamo dataset_id, possiamo usare pixel_id (spesso sono lo stesso) o chiamare API Graph direttamente
            # Per ora usiamo pixel_id (che funziona anche per dataset associati al pixel)
            # Se dataset_id è diverso da pixel_id, potremmo dover usare API Graph direttamente
            event_request = EventRequest(
                events=events,
                pixel_id=target_id  # Usa dataset_id se disponibile, altrimenti pixel_id
            )

            event_response = event_request.execute()
            logger.info(f"Meta event {event_name} sent to {'dataset' if self.dataset_id else 'pixel'} {target_id} (campaign_id={campaign_id}): {event_response}")
            return event_response

        except Exception as e:
            logger.error(f"Failed to send Meta event: {e}")
            return None
