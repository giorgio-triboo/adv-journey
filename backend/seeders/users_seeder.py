"""
Seeder per utenti iniziali.
Viene eseguito all'avvio dell'applicazione per assicurarsi che ci siano utenti nella whitelist.
"""
from database import SessionLocal
from models import User
import logging

logger = logging.getLogger(__name__)

# Lista degli utenti iniziali da creare
INITIAL_USERS = [
    {
        "email": "giorgio.contarini@triboo.it",
        "is_active": True,
        "role": "super-admin",
        "id_sede": "DIRECT"
    },
]


def seed_users():
    """
    Crea gli utenti iniziali se non esistono già.
    Aggiorna i dati se l'utente esiste ma ha valori diversi.
    """
    db = SessionLocal()
    try:
        created_count = 0
        updated_count = 0
        
        for user_data in INITIAL_USERS:
            # Verifica se l'utente esiste già
            existing_user = db.query(User).filter(User.email == user_data["email"]).first()
            
            if existing_user:
                # Aggiorna i dati se necessario (solo se sono diversi)
                needs_update = False
                
                if existing_user.is_active != user_data["is_active"]:
                    existing_user.is_active = user_data["is_active"]
                    needs_update = True
                
                if existing_user.role != user_data["role"]:
                    existing_user.role = user_data["role"]
                    needs_update = True
                
                if existing_user.id_sede != user_data.get("id_sede"):
                    existing_user.id_sede = user_data.get("id_sede")
                    needs_update = True
                
                if needs_update:
                    updated_count += 1
                    logger.info(f"Utente aggiornato: {user_data['email']}")
            else:
                # Crea nuovo utente
                new_user = User(
                    email=user_data["email"],
                    is_active=user_data["is_active"],
                    role=user_data["role"],
                    id_sede=user_data.get("id_sede")
                )
                db.add(new_user)
                created_count += 1
                logger.info(f"Utente creato: {user_data['email']} (ruolo: {user_data['role']})")
        
        # Commit una sola volta alla fine per migliori performance
        if created_count > 0 or updated_count > 0:
            db.commit()
            logger.info(f"Seeder utenti completato: {created_count} creati, {updated_count} aggiornati")
        else:
            logger.info("Tutti gli utenti iniziali sono già presenti nel database")
        
        return True
        
    except Exception as e:
        logger.error(f"Errore durante il seeding degli utenti: {e}", exc_info=True)
        db.rollback()
        return False
    finally:
        db.close()
