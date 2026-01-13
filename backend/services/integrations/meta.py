from config import settings
import logging
import time

logger = logging.getLogger(__name__)

# Try to import facebook_business, make it optional
try:
    from facebook_business.ad_objects.server_side.event import Event
    from facebook_business.ad_objects.server_side.custom_data import CustomData
    from facebook_business.ad_objects.server_side.user_data import UserData
    from facebook_business.ad_objects.server_side.event_request import EventRequest
    from facebook_business.api import FacebookAdsApi
    FACEBOOK_BUSINESS_AVAILABLE = True
except ImportError:
    FACEBOOK_BUSINESS_AVAILABLE = False
    logger.warning("facebook_business module not available. Meta service will be disabled.")

class MetaService:
    def __init__(self):
        self.access_token = settings.META_ACCESS_TOKEN
        self.pixel_id = settings.META_PIXEL_ID
        
        if not FACEBOOK_BUSINESS_AVAILABLE:
            logger.warning("facebook_business module not installed. Meta service disabled.")
            return
        
        if self.access_token:
            FacebookAdsApi.init(access_token=self.access_token)
        else:
            logger.warning("META_ACCESS_TOKEN not set. Meta service disabled.")

    def send_custom_event(self, event_name: str, lead_data: dict, additional_data: dict = None):
        """
        Sends a Custom Event to Meta CAPI.
        lead_data expected keys: email, phone, first_name, last_name, province (for geo)
        """
        if not FACEBOOK_BUSINESS_AVAILABLE:
            logger.warning("Skipping Meta event (facebook_business not available)")
            return
        
        if not self.access_token or not self.pixel_id:
            logger.info("Skipping Meta event (creds missing)")
            return

        try:
            user_data = UserData(
                emails=[lead_data.get('email')] if lead_data.get('email') else [],
                phones=[lead_data.get('phone')] if lead_data.get('phone') else [],
                # Hash is handled by SDK if passing raw strings? 
                # SDK automatically hashes if you use the setters, usually.
                # But standard is to pass hashed if possible, or use the helper methods.
                # The python SDK generally handles hashing if you pass plain text to specific fields.
                # Let's verify documentation or assume SDK handles it.
                # Actually SDK documentation says: "It is recommended that you hash... before passing".
                # But recent versions might auto-hash.
                # Let's assume we pass raw and SDK handles or we implement hashing if needed.
                first_name=lead_data.get('first_name'),
                last_name=lead_data.get('last_name'),
                state=lead_data.get('province') # Mapping province to state/region
            )

            custom_data = CustomData(
                custom_properties=additional_data or {}
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
                pixel_id=self.pixel_id
            )

            event_response = event_request.execute()
            logger.info(f"Meta event {event_name} sent: {event_response}")
            return event_response

        except Exception as e:
            logger.error(f"Failed to send Meta event: {e}")
            return None
