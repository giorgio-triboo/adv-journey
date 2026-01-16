#!/usr/bin/env python3
"""
Script per pulire i token OAuth Meta e le sessioni dal database.
Da eseguire dopo un reset completo del database.
"""
import sys
import os

# Aggiungi il path del backend al PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import MetaAccount
from sqlalchemy import update
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean_oauth_tokens():
    """Pulisce tutti i token OAuth Meta dal database (li imposta a NULL o stringa vuota)"""
    db = SessionLocal()
    
    try:
        # Conta quanti account hanno token
        count = db.query(MetaAccount).filter(MetaAccount.access_token.isnot(None)).count()
        logger.info(f"Trovati {count} account Meta con token OAuth")
        
        if count > 0:
            # Pulisci i token (imposta a NULL)
            db.query(MetaAccount).update({MetaAccount.access_token: None})
            db.commit()
            logger.info(f"✓ {count} token OAuth Meta rimossi dal database")
        else:
            logger.info("Nessun token OAuth da rimuovere")
        
        return True
        
    except Exception as e:
        logger.error(f"Errore durante la pulizia dei token: {e}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    logger.info("Pulizia token OAuth Meta dal database...")
    success = clean_oauth_tokens()
    if success:
        logger.info("✅ Pulizia completata con successo")
        sys.exit(0)
    else:
        logger.error("❌ Errore durante la pulizia")
        sys.exit(1)
