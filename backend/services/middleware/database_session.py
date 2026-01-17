"""Middleware per gestire sessioni dal database"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from database import SessionLocal
from services.utils.session_manager import get_session, update_session_activity, cleanup_expired_sessions, create_session
import logging
import time

logger = logging.getLogger('services.middleware.database_session')

# Cookie name per la sessione
SESSION_COOKIE_NAME = "session_id"

class DatabaseSessionMiddleware(BaseHTTPMiddleware):
    """
    Middleware che gestisce le sessioni dal database invece che dal server.
    Carica i dati della sessione dal database e li rende disponibili in request.session
    per compatibilità con il codice esistente.
    """
    
    async def dispatch(self, request: Request, call_next):
        # Inizializza session nello scope di Starlette (come fa SessionMiddleware)
        # Questo permette a request.session di funzionare correttamente
        # IMPORTANTE: deve essere fatto PRIMA di qualsiasi accesso a request.session
        request.scope["session"] = {}
        
        session_data = request.scope["session"]
        
        # Recupera session_id dal cookie
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        
        if session_id:
            db = SessionLocal()
            try:
                # Carica sessione dal database
                session = get_session(db, session_id)
                
                if session:
                    # Carica i dati della sessione nello scope per compatibilità
                    session_data.update(session.session_data.copy() if session.session_data else {})
                    session_data['_session_id'] = session_id
                    session_data['_user_id'] = session.user_id
                    
                    # Aggiorna ultima attività (solo se non è una richiesta statica)
                    if not request.url.path.startswith('/static'):
                        update_session_activity(db, session_id)
                else:
                    # Sessione non valida o scaduta - mantieni dict vuoto
                    # Il cookie verrà rimosso nella risposta
                    pass
                    
            except Exception as e:
                logger.error(f"Errore durante il caricamento della sessione: {e}", exc_info=True)
            finally:
                db.close()
        
        # Esegui la richiesta
        response = await call_next(request)
        
        # Gestisci cookie e salvataggio sessione
        if "session" in request.scope:
            session_data = request.scope["session"]
            session_id = session_data.get('_session_id')
            
            # Log per debug OAuth
            if request.url.path in ['/login', '/auth']:
                logger.debug(f"Middleware dopo richiesta {request.url.path}: session_id={session_id}, keys={list(session_data.keys())}")
            
            if session_id and session_data:
                # Salva i dati della sessione nel database
                db = SessionLocal()
                try:
                    from services.utils.session_manager import update_session_data
                    # Rimuovi solo i campi interni del middleware (non le chiavi OAuth di Authlib)
                    # Authlib usa chiavi che iniziano con _ per lo stato OAuth (es. _state_google)
                    # Quindi dobbiamo preservare quelle chiavi
                    internal_keys = {'_session_id', '_user_id'}
                    data_to_save = {k: v for k, v in session_data.items() 
                                   if k not in internal_keys}
                    update_session_data(db, session_id, data_to_save)
                except Exception as e:
                    logger.error(f"Errore durante il salvataggio della sessione: {e}", exc_info=True)
                finally:
                    db.close()
            elif not session_id and session_data:
                # Crea una sessione temporanea se ci sono dati nella sessione ma non c'è session_id
                # Questo è necessario per il flusso OAuth dove Authlib salva lo stato nella sessione
                # prima che l'utente sia autenticato
                db = SessionLocal()
                try:
                    # Rimuovi solo i campi interni del middleware (non le chiavi OAuth di Authlib)
                    # Authlib usa chiavi che iniziano con _ per lo stato OAuth (es. _state_google)
                    # Quindi dobbiamo preservare quelle chiavi
                    internal_keys = {'_session_id', '_user_id'}
                    data_to_save = {k: v for k, v in session_data.items() 
                                   if k not in internal_keys}
                    # Log per debug OAuth
                    oauth_keys = [k for k in data_to_save.keys() if 'oauth' in k.lower() or 'state' in k.lower() or 'google' in k.lower()]
                    if oauth_keys:
                        logger.info(f"Creazione sessione temporanea OAuth con chiavi: {oauth_keys}, tutte le chiavi: {list(data_to_save.keys())}")
                    # Crea sessione temporanea con user_id=0 (placeholder per OAuth non autenticato)
                    # La sessione verrà aggiornata con il vero user_id dopo l'autenticazione
                    temp_session = create_session(db, user_id=0, session_data=data_to_save)
                    session_id = temp_session.session_id
                    session_data['_session_id'] = session_id
                    session_data['_user_id'] = 0
                    # Imposta il cookie nella risposta
                    set_session_cookie(response, session_id)
                    logger.info(f"Sessione temporanea creata per OAuth: {session_id[:8]}... con {len(data_to_save)} chiavi")
                    # Verifica che il cookie sia stato impostato
                    cookie_set = any(cookie.name == SESSION_COOKIE_NAME for cookie in response.raw_headers if isinstance(cookie, tuple) and cookie[0] == b'set-cookie')
                    logger.debug(f"Cookie impostato nella risposta: {cookie_set}, session_id={session_id}")
                except Exception as e:
                    logger.error(f"Errore durante la creazione della sessione temporanea: {e}", exc_info=True)
                finally:
                    db.close()
            elif not session_id:
                # Rimuovi cookie se la sessione non è valida
                clear_session_cookie(response)
        
        # Pulisci sessioni scadute periodicamente (ogni 100 richieste circa)
        # Usa un timestamp per evitare di farlo su ogni richiesta
        if not hasattr(self, '_last_cleanup'):
            self._last_cleanup = 0
        
        current_time = time.time()
        if current_time - self._last_cleanup > 3600:  # Ogni ora
            db = SessionLocal()
            try:
                cleanup_expired_sessions(db)
                self._last_cleanup = current_time
            except Exception as e:
                logger.error(f"Errore durante la pulizia delle sessioni: {e}", exc_info=True)
            finally:
                db.close()
        
        return response

def set_session_cookie(response: Response, session_id: str, max_age: int = 3600 * 24 * 14):
    """
    Imposta il cookie della sessione nella risposta
    
    Args:
        response: Response object
        session_id: ID della sessione
        max_age: Durata del cookie in secondi (default: 14 giorni)
    """
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=max_age,
        httponly=True,
        secure=False,  # Cambia in True in produzione con HTTPS
        samesite='lax'
    )

def clear_session_cookie(response: Response):
    """
    Rimuove il cookie della sessione dalla risposta
    
    Args:
        response: Response object
    """
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=False,
        samesite='lax'
    )
