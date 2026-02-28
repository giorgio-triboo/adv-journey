#!/usr/bin/env python3
"""
Script per pulire tutti i dataset Meta salvati nel database.
Utile per fare test puliti.
"""
import sys
import os

# Aggiungi il path del backend al PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import MetaDataset
import logging
from logging_config import setup_logging

# Configura logging all'inizio
setup_logging(logging.INFO)
logger = logging.getLogger(__name__)

def clean_datasets():
    """Pulisce tutti i dataset Meta dal database"""
    db = SessionLocal()
    
    try:
        # Conta quanti dataset ci sono
        count = db.query(MetaDataset).count()
        logger.info(f"Trovati {count} dataset Meta nel database")
        
        if count > 0:
            # Elimina tutti i dataset
            db.query(MetaDataset).delete()
            db.commit()
            logger.info(f"✓ {count} dataset Meta rimossi dal database")
        else:
            logger.info("Nessun dataset da rimuovere")
        
        return True
        
    except Exception as e:
        logger.error(f"Errore durante la pulizia dei dataset: {e}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    logger.info("🧹 Pulizia dataset Meta...")
    success = clean_datasets()
    if success:
        logger.info("✅ Pulizia completata con successo")
        sys.exit(0)
    else:
        logger.error("❌ Errore durante la pulizia")
        sys.exit(1)
