"""Settings: Gestione Account Meta e OAuth"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from database import get_db
from models import MetaAccount, MetaCampaign, User
from sqlalchemy import func
from datetime import datetime, timedelta
import time
from config import settings
from services.integrations.meta_marketing import MetaMarketingService
from services.utils.crypto import encrypt_token, decrypt_token
from database import SessionLocal
import logging
import httpx
import secrets
import traceback
from ..common import templates, translate_error

logger = logging.getLogger('services.api.ui')

# region agent log
import json

DEBUG_LOG_PATH = "/Users/giorgio.contarini/contagio/direct/direct/cepu-lavorazioni/.cursor/debug-5b0c05.log"


def agent_debug_log(hypothesis_id: str, location: str, message: str, data: dict | None = None, run_id: str = "pre-fix") -> None:
    """
    Lightweight NDJSON logger for debug session 5b0c05.
    Writes directly to DEBUG_LOG_PATH; avoid logging secrets.
    """
    try:
        now_ms = int(time.time() * 1000)
        entry = {
            "sessionId": "5b0c05",
            "id": f"log_{now_ms}",
            "timestamp": now_ms,
            "location": location,
            "message": message,
            "data": data or {},
            "runId": run_id,
            "hypothesisId": hypothesis_id,
        }
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # Never break main flow for debug logging
        pass
# endregion agent log

router = APIRouter(include_in_schema=False)

def sync_meta_account_task(db: Session, account_id: str, access_token: str):
    """Background task per sincronizzazione account Meta"""
    try:
        logger.info(f"[SYNC TASK] Starting background sync task for account {account_id}")
        service = MetaMarketingService(access_token=access_token)
        logger.info(f"[SYNC TASK] MetaMarketingService initialized, calling sync_account_campaigns for {account_id}")
        service.sync_account_campaigns(account_id, db)
        logger.info(f"[SYNC TASK] Meta account {account_id} synced successfully")
    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error(f"[SYNC TASK] Meta account sync failed for {account_id}: {e}")
        logger.error(f"[SYNC TASK] Traceback: {error_traceback}")
    finally:
        try:
            db.close()
        except Exception as e:
            logger.warning(f"[SYNC TASK] Error closing DB session: {e}")

@router.get("/settings/meta-accounts")
async def settings_meta_accounts(request: Request, db: Session = Depends(get_db)):
    user_session = request.session.get('user')
    if not user_session:
        return RedirectResponse(url='/')
    
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    # Filtra account: mostra account condivisi (user_id IS NULL) + account dell'utente corrente
    accounts_query = db.query(MetaAccount).filter(
        (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user.id)
    )
    
    # Aggiungi conteggio campagne sincronizzate per ogni account
    accounts = []
    for account in accounts_query.all():
        # Conta campagne totali e sincronizzate per questo account
        total_campaigns = db.query(func.count(MetaCampaign.id)).filter(
            MetaCampaign.account_id == account.id
        ).scalar() or 0
        
        synced_campaigns = db.query(func.count(MetaCampaign.id)).filter(
            MetaCampaign.account_id == account.id,
            MetaCampaign.is_synced == True
        ).scalar() or 0
        
        # Aggiungi attributi dinamici all'oggetto account
        account.total_campaigns = total_campaigns
        account.synced_campaigns = synced_campaigns
        accounts.append(account)
    
    # Verifica se OAuth è configurato (opzionale - il token può essere usato direttamente)
    oauth_enabled = bool(settings.META_APP_ID and settings.META_APP_SECRET)
    
    # Verifica se c'è un token di sistema disponibile
    has_system_token = bool(settings.META_ACCESS_TOKEN)
    
    # Verifica se c'è un token OAuth valido nella sessione (per tornare alla selezione)
    has_valid_oauth_token = False
    token_expires = request.session.get('meta_oauth_token_expires')
    if token_expires and datetime.utcnow().timestamp() < token_expires:
        has_valid_oauth_token = bool(request.session.get('meta_oauth_token'))
    
    return templates.TemplateResponse("settings_meta_accounts.html", {
        "request": request,
        "title": "Gestione Account Meta",
        "user": current_user,
        "accounts": accounts,
        "active_page": "meta_accounts",
        "oauth_enabled": oauth_enabled,
        "has_system_token": has_system_token,
        "has_valid_oauth_token": has_valid_oauth_token
    })

@router.post("/settings/meta-accounts")
async def add_meta_account(request: Request, db: Session = Depends(get_db)):
    """Aggiunge account Meta. Usa token dal form o dal .env se disponibile."""
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    
    user_session = request.session.get('user')
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    if not current_user:
        return RedirectResponse(url='/')
    
    account_id = form.get("account_id", "").strip()
    access_token = form.get("access_token", "").strip()
    name = form.get("name", "").strip()
    
    # Se non è fornito un token nel form, usa quello dal .env (token di sistema)
    if not access_token and settings.META_ACCESS_TOKEN:
        access_token = settings.META_ACCESS_TOKEN
        logger.info(f"Usando token di sistema da META_ACCESS_TOKEN per account {account_id}")
    
    if not account_id:
        return RedirectResponse(url='/settings/meta-accounts?error=missing_account_id', status_code=303)
    
    if not access_token:
        return RedirectResponse(url='/settings/meta-accounts?error=missing_token', status_code=303)
    
    # Test connection
    service = MetaMarketingService(access_token=access_token)
    test_result = service.test_connection(account_id)
    
    if not test_result['success']:
        translated_error = translate_error(test_result["message"])
        return RedirectResponse(url=f'/settings/meta-accounts?error={translated_error}', status_code=303)
    
    # Cripta il token prima di salvarlo
    encrypted_token = encrypt_token(access_token)
    
    # Check if exists per questo utente (account condiviso o specifico)
    current_user_id = current_user.id if current_user else None
    existing = db.query(MetaAccount).filter(
        MetaAccount.account_id == account_id,
        (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user_id)
    ).first()
    
    if existing:
        existing.access_token = encrypted_token
        existing.name = test_result.get('account_name', name) or name
        existing.is_active = True
        existing.updated_at = datetime.utcnow()
    else:
        # Crea nuovo account per questo utente
        new_account = MetaAccount(
            account_id=account_id,
            name=test_result.get('account_name', name) or name,
            access_token=encrypted_token,
            user_id=current_user_id,  # Account specifico per questo utente
            is_active=True,
            sync_enabled=True
        )
        db.add(new_account)
    
    db.commit()
    return RedirectResponse(url='/settings/meta-accounts', status_code=303)

@router.post("/settings/meta-accounts/toggle")
async def toggle_meta_account(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    
    user_session = request.session.get('user')
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    current_user_id = current_user.id if current_user else None
    
    account_id = form.get("id")
    if account_id:
        account = db.query(MetaAccount).filter(
            MetaAccount.id == account_id,
            (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user_id)
        ).first()
        if account:
            account.is_active = not account.is_active
            account.updated_at = datetime.utcnow()
            db.commit()
    
    return RedirectResponse(url='/settings/meta-accounts', status_code=303)

@router.post("/settings/meta-accounts/delete")
async def delete_meta_account(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    
    user_session = request.session.get('user')
    current_user = db.query(User).filter(User.email == user_session.get('email')).first()
    current_user_id = current_user.id if current_user else None
    
    account_id = form.get("id")
    if account_id:
        # Puoi eliminare solo account tuoi (non quelli condivisi)
        db.query(MetaAccount).filter(
            MetaAccount.id == account_id,
            MetaAccount.user_id == current_user_id  # Solo account specifici utente, non condivisi
        ).delete()
        db.commit()
    
    return RedirectResponse(url='/settings/meta-accounts', status_code=303)

@router.post("/settings/meta-accounts/sync")
async def sync_meta_account(request: Request, db: Session = Depends(get_db)):
    if not request.session.get('user'): return RedirectResponse(url='/')
    form = await request.form()
    
    account_id = form.get("id")
    raw_redirect = form.get("redirect_url", "/settings/meta-accounts")
    # Validazione: accetta solo path relativi (no open redirect)
    redirect_url = raw_redirect if raw_redirect.startswith("/") and "//" not in raw_redirect else "/settings/meta-accounts"
    
    logger.info(f"Sync request received for account_id: {account_id}, redirect_url: {redirect_url}")
    
    if account_id:
        account = db.query(MetaAccount).filter(MetaAccount.id == account_id).first()
        if account and account.is_active:
            logger.info(f"Starting sync for account {account.account_id} ({account.name})")
            try:
                from tasks.meta_marketing import meta_sync_single_account_task
                meta_sync_single_account_task.delay(int(account_id))
                logger.info(f"Sync task queued for account {account.account_id}")
                
                # Se viene dalla pagina delle campagne, reindirizza lì con il filtro
                if "meta-campaigns" in redirect_url:
                    redirect_url = f"/settings/meta-campaigns?account_id={account.account_id}&sync_started=true"
                else:
                    # Aggiungi messaggio di successo per la pagina meta-accounts
                    redirect_url = f"/settings/meta-accounts?sync_started=true&account_name={account.name}"
            except Exception as e:
                logger.error(f"Error queuing sync for account {account.account_id}: {e}")
                redirect_url = f"/settings/meta-accounts?error=sync_failed&account_name={account.name}"
        else:
            logger.warning(f"Account {account_id} not found or not active")
            redirect_url = f"/settings/meta-accounts?error=account_not_found"
    else:
        logger.warning("Sync request without account_id")
        redirect_url = f"/settings/meta-accounts?error=missing_account_id"
    
    return RedirectResponse(url=redirect_url, status_code=303)

# Meta OAuth Endpoints
@router.get("/settings/meta-accounts/oauth/start")
async def meta_oauth_start(request: Request):
    """Inizia il flusso OAuth Meta"""
    if not request.session.get('user'):
        return RedirectResponse(url='/')
    
    if not settings.META_APP_ID or not settings.META_APP_SECRET:
        return RedirectResponse(url='/settings/meta-accounts?error=oauth_not_configured', status_code=303)
    
    # Genera state per CSRF protection
    state = secrets.token_urlsafe(32)
    request.session['meta_oauth_state'] = state
    
    # Scopes necessari per Meta Marketing API:
    # se META_SCOPES è impostato, usa quelli da .env (separati da virgola),
    # altrimenti fallback ai default.
    if settings.META_SCOPES:
        scopes = [s.strip() for s in settings.META_SCOPES.split(',') if s.strip()]
    else:
        scopes = [
            'ads_read',
            'ads_management',
            'business_management',
            'leads_retrieval',
            'pages_manage_ads',
            'pages_read_engagement',
            'pages_show_list',
        ]
    
    # URL di autorizzazione Meta
    # Usa APP_BASE_URL se configurato (per forzare https e ambiente corretto),
    # altrimenti fallback su request.base_url.
    if settings.APP_BASE_URL:
        base_url = settings.APP_BASE_URL.rstrip('/')
    else:
        base_url = str(request.base_url).rstrip('/')
    redirect_uri = f"{base_url}/settings/meta-accounts/oauth/callback"
    
    # Se disponibile, includi anche META_CONFIG_ID (nuovo flusso Config ID di Meta)
    config_part = f"config_id={settings.META_CONFIG_ID}&" if settings.META_CONFIG_ID else ""
    
    auth_url = (
        f"https://www.facebook.com/v23.0/dialog/oauth?"
        f"client_id={settings.META_APP_ID}&"
        f"{config_part}"
        f"redirect_uri={redirect_uri}&"
        f"scope={','.join(scopes)}&"
        f"state={state}&"
        f"response_type=code"
    )
    
    return RedirectResponse(url=auth_url, status_code=302)

@router.get("/settings/meta-accounts/oauth/callback")
async def meta_oauth_callback(request: Request, db: Session = Depends(get_db)):
    """Callback OAuth Meta - riceve il token e salva l'account"""
    if not request.session.get('user'):
        return RedirectResponse(url='/')
    
    # Verifica state per CSRF protection
    state = request.query_params.get('state')
    stored_state = request.session.get('meta_oauth_state')
    
    if not state or state != stored_state:
        return RedirectResponse(url='/settings/meta-accounts?error=invalid_state', status_code=303)
    
    # Rimuovi state dalla sessione
    request.session.pop('meta_oauth_state', None)
    
    code = request.query_params.get('code')
    error = request.query_params.get('error')
    
    if error:
        # Se l'utente ha annullato il flusso OAuth, non è un errore
        if error in ['access_denied', 'user_cancelled', 'user_denied']:
            return RedirectResponse(url='/settings/meta-accounts', status_code=303)
        # Per altri errori, traducili
        error_description = request.query_params.get('error_description', error)
        translated_error = translate_error(error_description)
        return RedirectResponse(url=f'/settings/meta-accounts?error={translated_error}', status_code=303)
    
    if not code:
        return RedirectResponse(url='/settings/meta-accounts?error=no_code', status_code=303)
    
    # Scambia code con access token
    if settings.APP_BASE_URL:
        base_url = settings.APP_BASE_URL.rstrip('/')
    else:
        base_url = str(request.base_url).rstrip('/')
    redirect_uri = f"{base_url}/settings/meta-accounts/oauth/callback"
    
    token_url = "https://graph.facebook.com/v23.0/oauth/access_token"
    token_params = {
        'client_id': settings.META_APP_ID,
        'client_secret': settings.META_APP_SECRET,
        'redirect_uri': redirect_uri,
        'code': code
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(token_url, params=token_params)
            response.raise_for_status()
            token_data = response.json()
            
            access_token = token_data.get('access_token')
            if not access_token:
                return RedirectResponse(url='/settings/meta-accounts?error=no_token', status_code=303)
            
            # Ottieni account disponibili per verificare che ci siano
            service = MetaMarketingService(access_token=access_token)
            accounts = service.get_accounts()
            
            if not accounts:
                return RedirectResponse(url='/settings/meta-accounts?error=no_accounts', status_code=303)
            
            # Salva token temporaneamente nella sessione (criptato) con timestamp
            # Il token scade dopo 10 minuti per sicurezza
            encrypted_token = encrypt_token(access_token)
            request.session['meta_oauth_token'] = encrypted_token
            request.session['meta_oauth_token_expires'] = (datetime.utcnow() + timedelta(minutes=10)).timestamp()
            
            # Redirect alla pagina di selezione account
            return RedirectResponse(url='/settings/meta-accounts/oauth/select', status_code=303)
            
    except httpx.HTTPStatusError as e:
        logger.error(f"Meta OAuth HTTP error: {e}")
        error_msg = f"Errore HTTP durante autenticazione: {e.response.status_code}"
        return RedirectResponse(url=f'/settings/meta-accounts?error={error_msg}', status_code=303)
    except Exception as e:
        logger.error(f"Meta OAuth callback error: {e}")
        error_msg = str(e).replace('&', 'e').replace('?', '')[:100]  # Sanitizza per URL
        return RedirectResponse(url=f'/settings/meta-accounts?error={error_msg}', status_code=303)

@router.get("/settings/meta-accounts/oauth/select")
async def meta_oauth_select_accounts(request: Request, db: Session = Depends(get_db)):
    """Pagina di selezione account Meta dopo OAuth"""
    if not request.session.get('user'):
        return RedirectResponse(url='/')
    
    # Verifica che il token sia ancora valido (max 10 minuti)
    token_expires = request.session.get('meta_oauth_token_expires')
    agent_debug_log(
        hypothesis_id="H1",
        location="meta_accounts.py:meta_oauth_select_accounts",
        message="select_accounts_token_check",
        data={
            "has_user": bool(request.session.get('user')),
            "token_expires": token_expires,
            "now_ts": datetime.utcnow().timestamp(),
        },
    )
    if not token_expires or datetime.utcnow().timestamp() > token_expires:
        request.session.pop('meta_oauth_token', None)
        request.session.pop('meta_oauth_token_expires', None)
        return RedirectResponse(url='/settings/meta-accounts?error=session_expired', status_code=303)
    
    encrypted_token = request.session.get('meta_oauth_token')
    if not encrypted_token:
        return RedirectResponse(url='/settings/meta-accounts?error=no_token', status_code=303)
    
    try:
        # Ottieni utente corrente
        current_user = db.query(User).filter(User.email == request.session.get('user', {}).get('email')).first()
        if not current_user:
            return RedirectResponse(url='/')
        current_user_id = current_user.id
        
        # Decripta e ottieni account
        decrypted_token = decrypt_token(encrypted_token)
        service = MetaMarketingService(access_token=decrypted_token)
        accounts = service.get_accounts()
        
        # Verifica quali account sono già presenti nel DB per questo utente
        # (account condivisi + account dell'utente)
        existing_accounts = {
            acc.account_id 
            for acc in db.query(MetaAccount).filter(
                (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user_id)
            ).all()
        }
        
        # Aggiungi flag per account esistenti e conta nuovi
        new_accounts_count = 0
        for account in accounts:
            account['already_added'] = account['account_id'] in existing_accounts
            if not account['already_added']:
                new_accounts_count += 1
        
        return templates.TemplateResponse("settings_meta_accounts_select.html", {
            "request": request,
            "title": "Seleziona Account Meta",
            "user": current_user,
            "accounts": accounts,
            "active_page": "meta_accounts",
            "new_accounts_count": new_accounts_count,
            "total_accounts": len(accounts)
        })
    except Exception as e:
        logger.error(f"Error loading accounts for selection: {e}")
        return RedirectResponse(url=f'/settings/meta-accounts?error={str(e)}', status_code=303)

@router.post("/settings/meta-accounts/oauth/save")
async def meta_oauth_save_accounts(request: Request, db: Session = Depends(get_db)):
    """Salva solo gli account selezionati dopo OAuth"""
    if not request.session.get('user'):
        return RedirectResponse(url='/')
    
    # Verifica token ancora valido
    token_expires = request.session.get('meta_oauth_token_expires')
    if not token_expires or datetime.utcnow().timestamp() > token_expires:
        request.session.pop('meta_oauth_token', None)
        request.session.pop('meta_oauth_token_expires', None)
        return RedirectResponse(url='/settings/meta-accounts?error=session_expired', status_code=303)
    
    encrypted_token = request.session.get('meta_oauth_token')
    if not encrypted_token:
        return RedirectResponse(url='/settings/meta-accounts?error=no_token', status_code=303)
    
    # Riusa il form già parsato dal middleware CSRF se disponibile,
    # altrimenti parsalo qui. In alcuni casi, una seconda chiamata a
    # request.form() può restituire un form "vuoto".
    form = getattr(request.state, "_parsed_form", None)
    if form is None:
        form = await request.form()
    # Estrai gli ID selezionati in modo robusto, indipendentemente dall'implementazione di FormData
    try:
        selected_account_ids = form.getlist('account_ids')  # type: ignore[attr-defined]
    except AttributeError:
        # Fallback se getlist non è disponibile
        selected_account_ids = [
            v for k, v in getattr(form, "multi_items", lambda: list(form.items()))()
            if k == "account_ids"
        ]

    # Log di debug in un logger "normale" che finisce in api-ui-YYYY-MM-DD.log
    logger.info(
        "[meta_oauth_save_accounts] START "
        f"user={request.session.get('user', {}).get('email')} "
        f"form_class={form.__class__.__name__} "
        f"form_keys={list(form.keys())} "
        f"selected_ids_len={len(selected_account_ids)} "
        f"selected_account_ids={selected_account_ids}"
    )
    
    if not selected_account_ids:
        logger.warning(
            "[meta_oauth_save_accounts] no_accounts_selected: "
            f"user={request.session.get('user', {}).get('email')} "
            f"form_keys={list(form.keys())}"
        )
        # Pulisci sessione e torna indietro
        request.session.pop('meta_oauth_token', None)
        request.session.pop('meta_oauth_token_expires', None)
        return RedirectResponse(url='/settings/meta-accounts?info=no_accounts_selected', status_code=303)
    
    try:
        # Ottieni utente corrente
        current_user = db.query(User).filter(User.email == request.session.get('user', {}).get('email')).first()
        if not current_user:
            return RedirectResponse(url='/')
        current_user_id = current_user.id
        
        decrypted_token = decrypt_token(encrypted_token)
        service = MetaMarketingService(access_token=decrypted_token)
        all_accounts = service.get_accounts()
        
        # Ottieni tutti gli account_id disponibili dall'API
        all_account_ids_from_api = {acc.get('account_id') for acc in all_accounts}
        
        # Ottieni tutti gli account già presenti per questo utente (condivisi + specifici)
        existing_user_accounts = db.query(MetaAccount).filter(
            (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user_id)
        ).all()
        
        # Cripta token per salvataggio
        encrypted_token_for_db = encrypt_token(decrypted_token)
        
        saved_count = 0
        removed_count = 0
        
        # Prima gestisci gli account selezionati (aggiungi/aggiorna)
        for account_data in all_accounts:
            account_id = account_data.get('account_id')
            if account_id in selected_account_ids:
                # Verifica se esiste già per questo utente (account condiviso o specifico)
                existing = db.query(MetaAccount).filter(
                    MetaAccount.account_id == account_id,
                    (MetaAccount.user_id == None) | (MetaAccount.user_id == current_user_id)
                ).first()
                
                if existing:
                    # Se esiste già come account condiviso, crea una copia per questo utente
                    # Se esiste già come account specifico utente, aggiornalo
                    if existing.user_id is None:
                        # Account condiviso: verifica se l'utente ha già una copia specifica
                        user_specific = db.query(MetaAccount).filter(
                            MetaAccount.account_id == account_id,
                            MetaAccount.user_id == current_user_id
                        ).first()
                        if user_specific:
                            # Aggiorna la copia specifica dell'utente
                            user_specific.access_token = encrypted_token_for_db
                            user_specific.name = account_data.get('name', user_specific.name)
                            user_specific.is_active = True
                            user_specific.updated_at = datetime.utcnow()
                        else:
                            # Crea copia per questo utente
                            new_account = MetaAccount(
                                account_id=account_id,
                                name=account_data.get('name', existing.name),
                                access_token=encrypted_token_for_db,
                                user_id=current_user_id,  # Account specifico per questo utente
                                is_active=True,
                                sync_enabled=True
                            )
                            db.add(new_account)
                    else:
                        # Account già specifico utente: aggiorna
                        existing.access_token = encrypted_token_for_db
                        existing.name = account_data.get('name', existing.name)
                        existing.is_active = True
                        existing.updated_at = datetime.utcnow()
                else:
                    # Crea nuovo account per questo utente (user_id = current_user_id)
                    # NULL = condiviso, user_id = specifico utente
                    new_account = MetaAccount(
                        account_id=account_id,
                        name=account_data.get('name', 'Unknown'),
                        access_token=encrypted_token_for_db,
                        user_id=current_user_id,  # Account specifico per questo utente
                        is_active=True,
                        sync_enabled=True
                    )
                    db.add(new_account)
                saved_count += 1
        
        # Poi gestisci gli account non selezionati (rimuovi solo quelli specifici dell'utente)
        for existing_account in existing_user_accounts:
            # Se l'account è disponibile dall'API ma non è stato selezionato, rimuovilo
            if existing_account.account_id in all_account_ids_from_api:
                if existing_account.account_id not in selected_account_ids:
                    # Rimuovi solo se è un account specifico dell'utente (non condiviso)
                    if existing_account.user_id == current_user_id:
                        db.delete(existing_account)
                        removed_count += 1
                    # Se è condiviso (user_id = NULL), non lo rimuoviamo (è condiviso tra utenti)
        
        db.commit()
        
        # Pulisci token dalla sessione
        request.session.pop('meta_oauth_token', None)
        request.session.pop('meta_oauth_token_expires', None)
        
        # Costruisci messaggio di successo
        success_parts = []
        if saved_count > 0:
            if saved_count == 1:
                success_parts.append(f"{saved_count} account aggiunto")
            else:
                success_parts.append(f"{saved_count} account aggiunti")
        if removed_count > 0:
            if removed_count == 1:
                success_parts.append(f"{removed_count} account rimosso")
            else:
                success_parts.append(f"{removed_count} account rimossi")
        
        if success_parts:
            success_msg = " e ".join(success_parts)
        else:
            success_msg = "Nessuna modifica effettuata"
        
        return RedirectResponse(url=f'/settings/meta-accounts?success={success_msg}', status_code=303)
        
    except Exception as e:
        logger.error(f"Error saving selected accounts: {e}")
        db.rollback()
        return RedirectResponse(url=f'/settings/meta-accounts?error={str(e)}', status_code=303)

@router.post("/settings/meta-accounts/test")
async def test_meta_account(request: Request, db: Session = Depends(get_db)):
    """Testa la connessione di un account Meta senza esporre il token"""
    if not request.session.get('user'):
        return JSONResponse({"success": False, "message": "Unauthorized"}, status_code=401)
    
    form = await request.form()
    
    account_id = form.get("id")
    if not account_id:
        return JSONResponse({"success": False, "message": "Account ID required"}, status_code=400)
    
    account = db.query(MetaAccount).filter(MetaAccount.id == account_id).first()
    if not account:
        return JSONResponse({"success": False, "message": "Account not found"}, status_code=404)
    
    try:
        # Decripta il token
        decrypted_token = decrypt_token(account.access_token)
        service = MetaMarketingService(access_token=decrypted_token)
        test_result = service.test_connection(account.account_id)
        
        return JSONResponse({
            "success": test_result['success'],
            "message": test_result.get('message', ''),
            "account_name": test_result.get('account_name', account.name)
        })
    except Exception as e:
        logger.error(f"Error testing Meta account {account_id}: {e}")
        return JSONResponse({
            "success": False,
            "message": f"Errore durante il test: {str(e)}"
        }, status_code=500)
