#!/usr/bin/env python3
"""
Script per configurare Mandrill come SMTP.
Esegui con: SMTP_PASSWORD=your_api_key python scripts/seed_mandrill_smtp.py

Oppure configura in .env e poi: python scripts/seed_mandrill_smtp.py
"""
import os
import sys

# Aggiungi backend al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import SMTPConfig
from services.utils.crypto import encrypt_token
from datetime import datetime


def main():
    host = os.getenv("SMTP_HOST", "smtp.mandrillapp.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "T-Direct SRL")
    password = os.getenv("SMTP_PASSWORD", "")
    from_email = os.getenv("SMTP_FROM_EMAIL", "insight@magellano.ai")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")

    if not password:
        print("ERRORE: SMTP_PASSWORD richiesto. Imposta la variabile d'ambiente:")
        print("  export SMTP_PASSWORD=md-0ph-xxxxx  # La tua API key Mandrill")
        print("  python scripts/seed_mandrill_smtp.py")
        sys.exit(1)

    db = SessionLocal()
    try:
        existing = db.query(SMTPConfig).filter(SMTPConfig.is_active == True).first()
        if existing:
            existing.host = encrypt_token(host)
            existing.port = port
            existing.user = encrypt_token(user)
            existing.password = encrypt_token(password)
            existing.from_email = encrypt_token(from_email) if from_email else None
            existing.use_tls = use_tls
            existing.updated_at = datetime.utcnow()
            print("Configurazione SMTP Mandrill aggiornata.")
        else:
            cfg = SMTPConfig(
                host=encrypt_token(host),
                port=port,
                user=encrypt_token(user),
                password=encrypt_token(password),
                from_email=encrypt_token(from_email) if from_email else None,
                use_tls=use_tls,
                is_active=True
            )
            db.add(cfg)
            print("Configurazione SMTP Mandrill creata.")
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Errore: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
