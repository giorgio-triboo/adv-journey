import zeep
from zeep import Client, Settings, xsd
from zeep.transports import Transport
import requests
import time
import os
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

from config import settings

class LeadStatus(BaseModel):
    status: str
    category: str
    raw_response: str
    checked_at: datetime

class UlixeClient:
    def __init__(self):
        self.session = requests.Session()
        self.transport = Transport(session=self.session)
        self.settings = Settings(strict=False, xml_huge_tree=True)
        self.client = Client(settings.ULIXE_WSDL, transport=self.transport, settings=self.settings)
        self.user = settings.ULIXE_USER
        self.password = settings.ULIXE_PASSWORD

    def get_lead_status(self, user_id_key: str) -> LeadStatus:
        """
        Queries StatoLead method.
        Rate limiting should be handled by the caller or a decorator.
        """
        try:
            # The method signature from WSDL usually takes parameters directly
            response = self.client.service.StatoLead(
                User=self.user,
                Pw=self.password,
                UserId=user_id_key
            )
            
            # Response is a string status
            status_str = str(response)
            
            category = self._categorize_status(status_str)
            
            return LeadStatus(
                status=status_str,
                category=category,
                raw_response=status_str,
                checked_at=datetime.utcnow()
            )
            
        except Exception as e:
            # Handle SOAP faults or network errors
            print(f"Error querying Ulixe for {user_id_key}: {e}")
            return LeadStatus(
                status="ERROR",
                category="unknown",
                raw_response=str(e),
                checked_at=datetime.utcnow()
            )

    def _categorize_status(self, status: str) -> str:
        """
        Categorizza lo stato Ulixe in categorie.
        Stati negativi (NO CRM): tutti quelli che iniziano con "NO CRM" o contengono "NO CRM"
        Stati positivi (CRM): CRM, CRM - FISSATO, CRM - SVOLTO, CRM – ACCETTATO
        Stati in lavorazione: In Lavorazione NV, Rif. N.V. (senza RIFIUTATO)
        """
        status_upper = status.upper()
        
        # Stati negativi: NO CRM (tutti i rifiutati)
        if "NO CRM" in status_upper:
            return "rifiutato"
        
        # Altri stati rifiutati
        if "RIFIUTATO" in status_upper or "NON INTERESSATO" in status_upper:
            return "rifiutato"

        # Stati in lavorazione (ancora in attesa)
        if "IN LAVORAZIONE" in status_upper or "RIF. N.V." in status_upper:
            if "RIFIUTATO" not in status_upper:  # Attention "Rif. N.V." vs "RIFIUTATO NV"
                return "in_lavorazione"

        # Stati positivi (CRM)
        if "CRM" in status_upper:
            if "SVOLTO" in status_upper or "ACCETTATO" in status_upper:
                return "finale"
            return "crm"  # Intermediate CRM status (CRM, CRM - FISSATO)

        return "unknown" 
