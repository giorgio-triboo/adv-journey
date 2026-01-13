"""
Utility per criptare e decriptare token sensibili.
Usa Fernet (symmetric encryption) per criptare i token prima di salvarli nel database.
"""
from cryptography.fernet import Fernet
from config import settings
import base64
import hashlib
import logging

logger = logging.getLogger(__name__)

# Genera una chiave stabile basata su SECRET_KEY
def _get_encryption_key() -> bytes:
    """Genera una chiave di criptazione stabile basata su SECRET_KEY."""
    secret = settings.SECRET_KEY.encode()
    # Usa SHA256 per generare una chiave di 32 bytes
    key = hashlib.sha256(secret).digest()
    # Fernet richiede una chiave base64-encoded di 32 bytes
    return base64.urlsafe_b64encode(key)

# Inizializza Fernet con la chiave
_fernet = Fernet(_get_encryption_key())

def encrypt_token(token: str) -> str:
    """
    Cripta un token usando Fernet.
    
    Args:
        token: Token in chiaro da criptare
        
    Returns:
        Token criptato come stringa
    """
    if not token:
        return ""
    
    try:
        encrypted = _fernet.encrypt(token.encode())
        return encrypted.decode()
    except Exception as e:
        logger.error(f"Error encrypting token: {e}")
        raise

def decrypt_token(encrypted_token: str) -> str:
    """
    Decripta un token criptato.
    
    Args:
        encrypted_token: Token criptato da decriptare
        
    Returns:
        Token in chiaro
    """
    if not encrypted_token:
        return ""
    
    try:
        decrypted = _fernet.decrypt(encrypted_token.encode())
        return decrypted.decode()
    except Exception as e:
        logger.error(f"Error decrypting token: {e}")
        # Se il token non è criptato (legacy), restituiscilo così com'è
        # Questo permette migrazione graduale
        return encrypted_token
