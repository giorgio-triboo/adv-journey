"""
Seeder per campagne Magellano.
Viene eseguito all'avvio dell'applicazione per assicurarsi che tutte le campagne siano presenti.

Struttura dati:
- Cliente: Nome del cliente/attività (identificatore principale, unique)
- ID MAGELLANO: Array di ID Magellano (es. [183] o [188,200,872,889,909])
- Pay: Livello pay
- ID MESSAGGIO: Array di oggetti con id e name (es. [{"id": "117410", "name": "CEPU"}, ...])
- Nome: Nome descrittivo (opzionale)

Logica:
- Un record per cliente/attività
- Gli ID Magellano sono memorizzati come array JSON
- Gli ID Messaggio sono memorizzati come array di oggetti JSON con id e name
- Permette di aggiungere facilmente nuovi ID Magellano o ID Messaggio a un cliente esistente
"""
from database import SessionLocal
from models import ManagedCampaign
import logging

logger = logging.getLogger(__name__)

# Mapping ID MESSAGGIO -> Nome
MSG_ID_TO_NAME = {
    "117410": "CEPU",
    "117341": "CEPU",
    "121234": "CEPU",
    "121199": "CEPU",
    "117405": "Psicologia",
    "117390": "Sport Management",
    "118600": "Scienze Educazione",
    "117404": "Scienze Motorie",
    "120479": "Scienze Turismo",
    "121177": "Ecampus Generica",
    "120827": "Ecampus Generica",
    "121236": "Ecampus Generica Uniclick",
    "120426": "Ecampus Generica",
    "117284": "Ecampus Generico",
    "117280": "Scienze Lavoro",
    "120427": "Digital Marketing",
    "120669": "Scienze Politiche Sociali",
    "120668": "Scienze Tec Psicologiche",
    "120464": "Criminologia",
    "120933": "Scienze Educazione",
    "121178": "Scienze Motorie",
    "122852": "Psicologia",
    "122856": "Scienze Educazione",
    "122853": "Scienze Motorie",
    "122854": "Sport Management",
    "123185": "Scienze Turismo Beni Culturali",
    "123186": "Scienze Bancarie",
    "123187": "Psicoeconomia",
    "123188": "Scienze Penitenziarie",
    "123189": "Scienze Politiche Sociali",
    "123190": "Servizi Giuridici D'impresa",
    "117393": "Ingegneria Informatica App",
    "122479": "Ingegneria AI",
    "120667": "Lingue Straniere",
    "120670": "Ingegneria Civile",
    "117518": "Ecampus Generica",
    "117786": "Fisioterapia",
    "117510": "Fisioterapia",
    "117511": "Fisioterapia",
    "121176": "Fisioterapia",
    "117383": "Grandi Scuole",
    "117270": "Grandi Scuole",
    "117497": "Grandi Scuole",
    "117309": "Grandi Scuole",
    "121237": "Grandi Scuole",
    "121662": "Grandi Scuole",
    "120666": "Grandi Scuole",
    "121235": "Grandi Scuole",
    "117409": "Grandi Scuole",
    "120097": "Grandi Scuole",
    "121501": "Grandi Scuole",
    "122851": "Grandi Scuole",
    "119977": "Link Campus",
}

# Dati campagne raggruppati per cliente
# Formato: Cliente, Pay, ID MAGELLANO (array), ID MESSAGGIO (array), Nome
CAMPAIGNS_DATA = [
    {
        "cliente": "CEPU",
        "pay": "80",
        "magellano_ids": ["183"],
        "msg_ids": ["117410", "117341", "121234", "121199"],
        "nome": "CEPU"
    },
    {
        "cliente": "ECAMPUS",
        "pay": "40",
        "magellano_ids": ["188", "200", "872", "889", "909"],
        "msg_ids": [
            "117405", "117390", "118600", "117404", "120479",
            "121177", "120827", "121236", "120426", "117284",
            "117280", "120427", "120669", "120668", "120464",
            "120933", "121178", "122852", "122856", "122853",
            "122854", "123185", "123186", "123187", "123188",
            "123189", "123190", "117393", "122479", "120667",
            "120670", "117518"
        ],
        "nome": "ECAMPUS"
    },
    {
        "cliente": "FISIOTERAPIA",
        "pay": "35",
        "magellano_ids": ["199"],
        "msg_ids": ["117786", "117510", "117511", "121176"],
        "nome": "Fisioterapia"
    },
    {
        "cliente": "GS",
        "pay": "60",
        "magellano_ids": ["190", "578", "618", "829", "836", "870"],
        "msg_ids": [
            "117383", "117270", "117497", "117309", "121237",
            "121662", "120666", "121235", "117409", "120097",
            "121501", "122851"
        ],
        "nome": "Grandi Scuole"
    },
    {
        "cliente": "LINK CAMPUS",
        "pay": "40",
        "magellano_ids": ["423"],
        "msg_ids": ["119977"],
        "nome": "Link Campus"
    },
]

def convert_msg_ids_to_objects(msg_ids_list):
    """Converte lista di ID Messaggio in array di oggetti con id e name"""
    return [{"id": msg_id, "name": MSG_ID_TO_NAME.get(msg_id, msg_id)} for msg_id in msg_ids_list]

def seed_campaigns():
    """
    Aggiunge/aggiorna le campagne Magellano nel database.
    
    Logica:
    - Un record per cliente/attività (cliente_name è unique)
    - Gli ID Magellano sono memorizzati come array JSON
    - Gli ID Messaggio sono memorizzati come array di oggetti JSON con id e name
    - Se il cliente esiste già, aggiorna i campi
    """
    db = SessionLocal()
    try:
        added = 0
        updated = 0
        
        for camp_data in CAMPAIGNS_DATA:
            cliente_name = camp_data.get("cliente")
            
            # Converti msg_ids in array di oggetti
            msg_ids_raw = camp_data.get("msg_ids", [])
            msg_ids_objects = convert_msg_ids_to_objects(msg_ids_raw)
            
            # Cerca record esistente per cliente_name
            existing = db.query(ManagedCampaign).filter(
                ManagedCampaign.cliente_name == cliente_name
            ).first()
            
            if existing:
                # Update existing
                needs_update = False
                
                # Aggiorna nome se diverso
                if existing.name != camp_data.get("nome"):
                    existing.name = camp_data.get("nome")
                    needs_update = True
                
                # Aggiorna pay_level se diverso
                if existing.pay_level != camp_data.get("pay"):
                    existing.pay_level = camp_data.get("pay")
                    needs_update = True
                
                # Aggiorna magellano_ids se diversi (confronta come set per ignorare ordine)
                new_mag_ids = set(camp_data.get("magellano_ids", []))
                existing_mag_ids = set(existing.magellano_ids or [])
                if new_mag_ids != existing_mag_ids:
                    existing.magellano_ids = camp_data.get("magellano_ids", [])
                    needs_update = True
                
                # Aggiorna msg_ids se diversi o se sono ancora nella vecchia struttura (stringhe)
                # Estrai solo gli ID dagli oggetti esistenti per confronto
                existing_msg_ids = set()
                is_old_format = False
                if existing.msg_ids:
                    for msg in existing.msg_ids:
                        if isinstance(msg, dict):
                            existing_msg_ids.add(msg.get("id", ""))
                        else:
                            # Retrocompatibilità: se è una stringa, trattala come ID
                            existing_msg_ids.add(str(msg))
                            is_old_format = True
                
                new_msg_ids_set = set(msg_ids_raw)
                # Forza aggiornamento se formato vecchio o se gli ID sono diversi
                if is_old_format or new_msg_ids_set != existing_msg_ids:
                    existing.msg_ids = msg_ids_objects
                    # Sincronizza anche ulixe_ids con gli ID (non gli oggetti)
                    existing.ulixe_ids = msg_ids_raw
                    needs_update = True
                
                if needs_update:
                    updated += 1
                
                # Ensure it's active
                if not existing.is_active:
                    existing.is_active = True
                    updated += 1
            else:
                # Crea nuovo record
                new_campaign = ManagedCampaign(
                    cliente_name=cliente_name,
                    name=camp_data.get("nome"),
                    magellano_ids=camp_data.get("magellano_ids", []),
                    msg_ids=msg_ids_objects,
                    pay_level=camp_data.get("pay"),
                    is_active=True,
                    ulixe_ids=msg_ids_raw  # Sincronizzato con msg_ids
                )
                db.add(new_campaign)
                added += 1
        
        db.commit()
        if added > 0 or updated > 0:
            logger.info(f"Campaigns seeder: {added} added, {updated} updated")
        return True
        
    except Exception as e:
        logger.error(f"Error seeding campaigns: {e}", exc_info=True)
        db.rollback()
        return False
    finally:
        db.close()
