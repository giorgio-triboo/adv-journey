"""
Utility per criptare e decriptare token sensibili.
Usa Fernet (symmetric encryption) per criptare i token prima di salvarli nel database.
Inoltre fornisce funzioni per hashar dati secondo le specifiche Meta Conversion API.
"""
from cryptography.fernet import Fernet
from config import settings
import base64
import hashlib
import logging
import re

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

def normalize_email_for_meta(email: str) -> str:
    """
    Normalizza un'email secondo le specifiche Meta Conversion API.
    
    Regole Meta:
    - Trim leading and trailing spaces
    - Convert all characters to lowercase
    
    Args:
        email: Email da normalizzare
        
    Returns:
        Email normalizzata o stringa vuota se input non valido
    """
    if not email:
        return ""
    
    # Trim e lowercase
    normalized = email.strip().lower()
    return normalized

def normalize_phone_for_meta(phone: str) -> str:
    """
    Normalizza un numero di telefono secondo le specifiche Meta Conversion API.
    
    Regole Meta:
    - Rimuovere tutti i caratteri non numerici (spazi, parentesi, trattini, ecc.)
    - Mantenere solo le cifre
    
    Args:
        phone: Numero di telefono da normalizzare
        
    Returns:
        Numero normalizzato (solo cifre) o stringa vuota se input non valido
    """
    if not phone:
        return ""
    
    # Rimuovi tutti i caratteri non numerici
    normalized = re.sub(r'\D', '', phone)
    return normalized

def hash_for_meta(value: str) -> str:
    """
    Hasha un valore normalizzato usando SHA256 secondo le specifiche Meta.
    
    Args:
        value: Valore già normalizzato da hashar
        
    Returns:
        Hash SHA256 in formato esadecimale lowercase, o stringa vuota se input vuoto
    """
    if not value:
        return ""
    
    # SHA256 hash in lowercase hex
    hash_obj = hashlib.sha256(value.encode('utf-8'))
    return hash_obj.hexdigest().lower()

def hash_email_for_meta(email: str) -> str:
    """
    Normalizza e hasha un'email secondo le specifiche Meta Conversion API.
    
    Args:
        email: Email da hashar
        
    Returns:
        Hash SHA256 dell'email normalizzata, o stringa vuota se input non valido
    """
    normalized = normalize_email_for_meta(email)
    if not normalized:
        return ""
    return hash_for_meta(normalized)

def hash_phone_for_meta(phone: str) -> str:
    """
    Normalizza e hasha un numero di telefono secondo le specifiche Meta Conversion API.
    
    Args:
        phone: Numero di telefono da hashar
        
    Returns:
        Hash SHA256 del telefono normalizzato, o stringa vuota se input non valido
    """
    normalized = normalize_phone_for_meta(phone)
    if not normalized:
        return ""
    return hash_for_meta(normalized)
