import os
import logging
import zipfile
import tempfile
import shutil
import pandas as pd
from playwright.sync_api import sync_playwright
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional

from config import settings

# Usa il logger configurato centralmente
logger = logging.getLogger('services.integrations.magellano')

class MagellanoService:
    def __init__(self, headless: bool = True):
        self.base_url = "https://magellano.ai/admin/index.php"
        self.username = settings.MAGELLANO_USER
        self.password = settings.MAGELLANO_PASSWORD
        self.headless = headless

    def generate_password(self, file_date: Optional[date] = None) -> str:
        """Generates dynamic ZIP password: ddmmyyyyT-Direct"""
        if file_date is None:
            file_date = date.today()
        return file_date.strftime("%d%m%Y") + "T-Direct"
    
    def process_uploaded_file(self, file_path: str, file_date: date, campaign_id: Optional[int] = None, original_filename: Optional[str] = None) -> List[Dict]:
        """
        Processa un file ZIP o CSV/Excel uploadato manualmente.
        IMPORTANT: All extracted files are automatically deleted after ingestion.
        
        Args:
            file_path: Path del file uploadato
            file_date: Data per calcolare la password ZIP
            campaign_id: ID campagna (opzionale, può essere estratto dal file)
            original_filename: Nome originale del file (per estrarre campaign_id se non fornito)
        
        Returns:
            Lista di dict con i dati delle lead processate
        """
        temp_dir = tempfile.mkdtemp()
        extracted_files = []  # Traccia file estratti per eliminarli dopo
        try:
            leads = []
            
            # Se è un ZIP, estrailo
            if file_path.endswith('.zip'):
                password_used = self.generate_password(file_date)
                logger.info(f"Tentativo estrazione ZIP: file={os.path.basename(file_path)}, data={file_date}")
                xls_path = self._extract_zip_with_password(file_path, temp_dir, file_date)
                if not xls_path:
                    raise Exception(f"Impossibile estrarre il file ZIP (formato password: ddmmyyyyT-Direct). Verifica che la data fornita ({file_date}) corrisponda alla data usata per creare il file ZIP.")
                extracted_files.append(xls_path)
            elif file_path.endswith(('.xls', '.xlsx', '.csv')):
                xls_path = file_path
            else:
                raise Exception("Formato file non supportato. Usa .zip, .xls, .xlsx o .csv")
            
            # Processa il file Excel/CSV
            if campaign_id:
                leads = self._process_excel(xls_path, campaign_id)
            else:
                # Prova a estrarre campaign_id dal nome file originale o dal nome temporaneo
                # Es: export-188-11012026.xls -> campaign_id = 188
                # Gestisce anche: export-199-15012026 (1).zip
                import re
                # Usa il nome originale se disponibile, altrimenti usa il nome del file temporaneo
                filename = original_filename if original_filename else os.path.basename(file_path)
                # Regex migliorata: cerca "export-" seguito da numeri, anche se ci sono spazi o parentesi dopo
                match = re.search(r'export-(\d+)', filename)
                if match:
                    campaign_id = int(match.group(1))
                    logger.info(f"Estratto campaign_id {campaign_id} dal nome file: {filename}")
                    leads = self._process_excel(xls_path, campaign_id)
                else:
                    # Se non troviamo il campaign_id, usiamo un default o solleviamo errore
                    raise Exception(f"Impossibile determinare l'ID campagna dal nome file '{filename}'. Fornisci l'ID campagna o usa un nome file con formato 'export-{{campaign_id}}-{{date}}.xls'")
            
            # Elimina file estratti dopo l'ingestion (solo quelli in temp_dir, non il file originale)
            for extracted_file in extracted_files:
                try:
                    if os.path.exists(extracted_file) and extracted_file.startswith(temp_dir):
                        os.unlink(extracted_file)
                        logger.info(f"Deleted extracted file after ingestion: {extracted_file}")
                except Exception as e:
                    logger.warning(f"Could not delete extracted file {extracted_file}: {e}")
            
            return leads
            
        finally:
            # Elimina sempre la directory temporanea e tutto il contenuto
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    logger.info(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Could not remove temp directory {temp_dir}: {e}")
    
    def _extract_zip_with_password(self, zip_path: str, extract_to: str, file_date: date) -> Optional[str]:
        """Estrae un file ZIP con password basata sulla data fornita"""
        try:
            password = self.generate_password(file_date)
            logger.info(f"Tentativo estrazione ZIP: file={os.path.basename(zip_path)}, data={file_date}")
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(extract_to, pwd=password.encode('utf-8'))
                
            for root, _, files in os.walk(extract_to):
                for f in files:
                    if f.endswith('.xls') or f.endswith('.xlsx'):
                        logger.info(f"File Excel estratto: {os.path.join(root, f)}")
                        return os.path.join(root, f)
            logger.warning(f"Nessun file Excel trovato nel ZIP estratto in {extract_to}")
            return None
        except zipfile.BadZipFile as e:
            logger.error(f"File ZIP non valido o corrotto: {e}")
            return None
        except RuntimeError as e:
            if "Bad password" in str(e) or "Bad CRC" in str(e):
                logger.error(f"Password errata per ZIP (data: {file_date})")
            else:
                logger.error(f"Errore durante estrazione ZIP: {e}")
            return None
        except Exception as e:
            logger.error(f"ZIP extraction failed: {e}")
            return None

    def fetch_leads(self, start_date: date, end_date: date, campaigns: List[int], job_id: int | None = None) -> List[Dict]:
        """
        Orchestrates the download and parsing of leads from Magellano.
        IMPORTANT: All downloaded files (ZIP, XLS) are automatically deleted after ingestion.
        """
        all_leads = []
        temp_dir = tempfile.mkdtemp()
        
        try:
            with sync_playwright() as p:
                for campaign in campaigns:
                    logger.info(f"Processing campaign {campaign}...")
                    zip_path = self._download_campaign(
                        p,
                        campaign,
                        start_date,
                        end_date,
                        temp_dir,
                        headless=self.headless,
                        job_id=job_id,
                    )
                    
                    if not zip_path:
                        logger.error(f"Failed to download ZIP for campaign {campaign}")
                        continue

                    xls_path = self._extract_zip(zip_path, temp_dir)
                    if not xls_path:
                        logger.error(f"Failed to extract XLS for campaign {campaign}")
                        # Elimina ZIP anche se l'estrazione fallisce
                        try:
                            if os.path.exists(zip_path):
                                os.unlink(zip_path)
                                logger.info(f"Deleted failed ZIP file: {zip_path}")
                        except Exception as e:
                            logger.warning(f"Could not delete ZIP file {zip_path}: {e}")
                        continue
                    
                    # Processa Excel
                    leads = self._process_excel(xls_path, campaign)
                    all_leads.extend(leads)
                    
                    # Elimina esplicitamente ZIP e XLS dopo l'ingestion
                    try:
                        if os.path.exists(zip_path):
                            os.unlink(zip_path)
                            logger.info(f"Deleted ZIP file after ingestion: {zip_path}")
                        if os.path.exists(xls_path) and xls_path != zip_path:
                            os.unlink(xls_path)
                            logger.info(f"Deleted XLS file after ingestion: {xls_path}")
                    except Exception as e:
                        logger.warning(f"Could not delete files after ingestion: {e}")
                    
        except Exception as e:
            logger.error(f"Error in fetch_leads: {e}")
            raise e
        finally:
            # Elimina sempre la directory temporanea e tutto il contenuto
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    logger.info(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Could not remove temp directory {temp_dir}: {e}")
            
        return all_leads

    def _download_campaign(
        self,
        playwright,
        campaign_id: int,
        start_date: date,
        end_date: date,
        download_dir: str,
        headless: bool = True,
        job_id: int | None = None,
    ) -> Optional[str]:
        browser = playwright.chromium.launch(
            headless=headless,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        context = browser.new_context(
            viewport={'width': 1400, 'height': 900},
            accept_downloads=True,
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = context.new_page()
        
        # Nome file custom per export, univoco per job:
        # export-<ID_CAMPAGNA>-<DATA_INIZIO>-<DATA_FINE>_<JOB_ID>
        start_date_str = start_date.strftime('%d%m%Y')
        end_date_str = end_date.strftime('%d%m%Y')
        if job_id is not None:
            export_filename = f"export-{campaign_id}-{start_date_str}-{end_date_str}_{job_id}"
        else:
            # Fallback (esecuzioni manuali / script locali) senza job_id
            export_filename = f"export-{campaign_id}-{start_date_str}-{end_date_str}"
        export_filename_xls = f"{export_filename}.xls"
        
        # Gestione dialog per nome file
        page.on("dialog", lambda dialog: dialog.accept(export_filename) if dialog.type == "prompt" else dialog.accept())
        
        try:
            # Login
            logger.info("Logging in to Magellano...")
            page.goto(f"{self.base_url}?menuNode=15.04&module=importPanelPublisher&method=main")
            page.fill("#weblib_username", self.username)
            page.fill("#weblib_password", self.password)
            page.click("a[href*='form_login'].btn-primary")
            page.wait_for_load_state('networkidle')
            
            # Navigate to Campaigns
            logger.info("Navigating to Campaigns...")
            page.goto(f"{self.base_url}?menuNode=05.01&module=listCoregs&method=main")
            page.wait_for_load_state('networkidle')
            
            # Filter Campaign using Select2 (from user feedback & automation script)
            logger.info(f"Filtering for campaign {campaign_id}...")
            # Check if filter section is collapsed
            plus_icon = page.locator('a[data-rel="collapse"] i.fa-plus')
            if plus_icon.is_visible():
                plus_icon.click()
                page.wait_for_timeout(1000)
            
            # Use Select2 choices for Campaign field
            page.evaluate(f"""
                $('.select2-choices').click();
                setTimeout(function() {{
                    $('.select2-input').val('{campaign_id}').trigger('input').trigger('keyup');
                }}, 500);
            """)
            page.wait_for_timeout(2000)
            # Click the result that matches the campaign ID
            page.click(f'.select2-result-label:has-text("{campaign_id}")', timeout=5000)
            
            page.click('a.btn-success:has-text("Apply filters")')
            page.wait_for_load_state('networkidle')
            
            # Go to Users
            logger.info("Opening Users list for campaign...")
            page.locator('button[data-original-title="Users"] i.fa-users').first.click()
            page.wait_for_load_state('networkidle')
            
            # Inserisci date direttamente nei campi (formato DD/MM/YYYY come data-date-format)
            date_from_str = start_date.strftime('%d/%m/%Y')
            date_to_str = end_date.strftime('%d/%m/%Y')
            logger.info(f"Setting dates: {date_from_str} - {date_to_str} (#filters_date_from, #filters_date_to)")
            page.locator('#filters_date_from').fill(date_from_str)
            page.locator('#filters_date_to').fill(date_to_str)
            # Trigger change per Bootstrap datepicker
            page.evaluate("""
                const fromEl = document.getElementById('filters_date_from');
                const toEl = document.getElementById('filters_date_to');
                if (fromEl) { $(fromEl).trigger('change'); }
                if (toEl) { $(toEl).trigger('change'); }
            """)
            page.wait_for_timeout(500)
            
            # IMPORTANTE: Resetta esplicitamente il filtro "Sent" a vuoto per recuperare TUTTE le lead
            # (anche quelle scartate, firewall, refused, etc.)
            page.evaluate("""
                const select = document.getElementById('filters_sent');
                if (select) {
                    select.value = '';  // Vuoto = tutte le lead
                    $(select).trigger('change');
                }
            """)
            page.wait_for_timeout(500)
            
            page.click('a.btn-success:has-text("Apply filters")')
            page.wait_for_load_state('networkidle')
            
            # Export
            logger.info("Initializing Export...")
            page.click('a.btn-primary:has-text("Export")')
            page.wait_for_timeout(3000)
            
            # Navigate to Exports List
            logger.info("Checking Export List...")
            page.goto(f"{self.base_url}?menuNode=10.07&module=listExportsList&method=main")
            
            download_path = None
            found = False
            for attempt in range(20):
                page.reload()
                page.wait_for_load_state('networkidle')
                rows = page.locator('table#table-basic tr').all()
                for row in rows:
                    row_text = row.inner_text()
                    if export_filename_xls in row_text and "completed" in row_text.lower():
                        logger.info(f"File {export_filename_xls} ready. Downloading...")
                        with page.expect_download() as download_info:
                            row.locator('button[data-original-title="Download"]').click()
                        download = download_info.value
                        download_path = os.path.join(download_dir, download.suggested_filename)
                        download.save_as(download_path)
                        found = True
                        break
                if found: break
                logger.info(f"Wait attempt {attempt + 1}: export still pending...")
                page.wait_for_timeout(3000)
            
            return download_path

        except Exception as e:
            logger.error(f"Magellano automation failed: {e}")
            return None
        finally:
            browser.close()

    def _extract_zip(self, zip_path, extract_to) -> Optional[str]:
        """Estrae ZIP usando password di oggi (per sync automatica)"""
        return self._extract_zip_with_password(zip_path, extract_to, date.today())

    def _normalize_magellano_status(self, status_raw: Optional[str]) -> str:
        """
        Normalizza lo stato Magellano in uno stato standardizzato.
        
        Stati principali:
        - magellano_sent: "Sent (accept from WS or by email)" → IN_LAVORAZIONE (Accettato FW)
        - magellano_firewall: "Blocked by firewall" → RIFIUTATO (Scartato FW)
        - magellano_refused: "Refused (from WS)" → RIFIUTATO (Scartato FW)
        - magellano_waiting: "Waiting Marketing Automation" → RIFIUTATO (Scartato FW)
        - magellano_unknown: per stati non riconosciuti o None → RIFIUTATO (Scartato FW)
        """
        if not status_raw:
            return "magellano_unknown"
        
        status_lower = status_raw.lower().strip()
        
        # Stati principali
        if "sent" in status_lower and ("accept" in status_lower or "ws" in status_lower or "email" in status_lower):
            return "magellano_sent"
        elif "firewall" in status_lower or "blocked" in status_lower:
            return "magellano_firewall"
        elif "refused" in status_lower:
            return "magellano_refused"
        elif "waiting" in status_lower and "marketing" in status_lower:
            return "magellano_waiting"
        else:
            # Per altri stati, crea un nome normalizzato
            normalized = status_lower.replace(' ', '_').replace('-', '_')
            return f"magellano_{normalized}"
    
    def _get_magellano_status_category(self, magellano_status: str):
        """
        Calcola la categoria normalizzata per lo stato Magellano.
        
        Regole:
        - magellano_sent → IN_LAVORAZIONE (Accettato FW)
        - magellano_firewall, magellano_refused, magellano_waiting, magellano_unknown → RIFIUTATO (Scartato FW)
        """
        from models import StatusCategory
        
        if magellano_status == 'magellano_sent':
            return StatusCategory.IN_LAVORAZIONE
        else:
            # Tutti gli altri stati (firewall, refused, waiting, unknown) → RIFIUTATO
            return StatusCategory.RIFIUTATO

    def _process_excel(self, xls_path, campaign_id) -> List[Dict]:
        try:
            # Supporta sia Excel che CSV
            lower_path = str(xls_path).lower()
            if lower_path.endswith(".csv"):
                df = pd.read_csv(xls_path)
            else:
                df = pd.read_excel(xls_path)
            leads = []
            
            # Mappa colonne normalizzate (lowercase, stripped) per essere robusti a maiuscole/spazi
            normalized_columns = {str(col).strip().lower(): col for col in df.columns}
            # Prova a individuare la colonna dello stato con diversi alias possibili
            status_col = None
            for candidate in ["sent status", "status", "stato", "lead_status", "lead status"]:
                if candidate in normalized_columns:
                    status_col = normalized_columns[candidate]
                    break
            
            # Colonna data iscrizione: export Magellano "Subscr. date" (formato "2026-01-28 20:35:42")
            subscr_date_col = None
            # Prima prova con alias noti su nomi normalizzati
            for candidate in ["subscr. date", "subscr_date", "subscription date", "subscr date"]:
                if candidate in normalized_columns:
                    subscr_date_col = normalized_columns[candidate]
                    break
            # Fallback robusto: cerca qualunque colonna che contenga "subscr" e "date"
            if not subscr_date_col:
                for col in df.columns:
                    name_norm = str(col).strip().lower()
                    compact = name_norm.replace(" ", "").replace(".", "").replace("_", "")
                    if ("subscr" in name_norm and "date" in name_norm) or compact == "subscrdate":
                        subscr_date_col = col
                        break
            if not subscr_date_col:
                logger.warning(
                    f"Colonna 'Subscr. date' non trovata in file Magellano {xls_path}. "
                    f"Colonne disponibili: {list(df.columns)}"
                )
            else:
                logger.info(f"Colonna data iscrizione Magellano trovata: {repr(subscr_date_col)}")
            
            if not status_col:
                # Log di debug per capire perché gli stati risultano tutti unknown
                logger.warning(
                    f"Colonna 'Status' non trovata in file Magellano {xls_path}. "
                    f"Colonne disponibili: {list(df.columns)}"
                )
            
            # Colonne con ID Meta (se presenti): facebook_*_id
            campaign_id_col = normalized_columns.get("facebook_campaign_name_id")
            adset_id_col = normalized_columns.get("facebook_ad_set_id") or normalized_columns.get(
                "facebook_adset_id"
            )
            ad_id_col = normalized_columns.get("facebook_ad_name_id")
            
            for _, row in df.iterrows():
                # Map based on identified columns from inspection
                email = str(row.get('Email', '')).strip()
                if not email or pd.isna(row.get('Email')):
                    continue
                
                # External User ID is a good candidate for dedup
                ext_user_id = str(row.get('Id user', ''))
                
                # Estrai e normalizza lo stato Magellano in modo robusto (case-insensitive, alias)
                status_raw = None
                if status_col:
                    raw_val = row.get(status_col, None)
                    if raw_val is not None and not pd.isna(raw_val):
                        status_raw = str(raw_val).strip()
                magellano_status = self._normalize_magellano_status(status_raw)
                magellano_status_category = self._get_magellano_status_category(magellano_status)

                # Estrai data iscrizione Magellano (Subscr. date): formato "2026-01-28 20:35:42" → solo date
                magellano_subscr_date = None
                if subscr_date_col:
                    raw_date = row.get(subscr_date_col, None)
                    if raw_date is not None and not pd.isna(raw_date):
                        try:
                            # Oggetto con .date() (pandas Timestamp, datetime)
                            if hasattr(raw_date, "date"):
                                magellano_subscr_date = raw_date.date()
                            else:
                                # Stringa: formato Magellano "2026-01-28 20:35:42" o "2026-01-28"
                                s = str(raw_date).strip()
                                if s:
                                    parsed = pd.to_datetime(s, format="%Y-%m-%d %H:%M:%S", errors="coerce")
                                    if pd.isna(parsed):
                                        parsed = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
                                    if pd.isna(parsed):
                                        parsed = pd.to_datetime(s, errors="coerce")
                                    if parsed is not None and not pd.isna(parsed):
                                        magellano_subscr_date = parsed.date()
                        except Exception as e:
                            logger.warning(f"Impossibile parsare Subscr. date '{raw_date}': {e}")
                
                # Log prima riga per debug data (solo una volta)
                if not leads and subscr_date_col:
                    logger.info(
                        f"Subscr. date esempio: raw={repr(raw_date)}, parsed={magellano_subscr_date}"
                    )
                
                # Mantieni compatibilità con payout_status per retrocompatibilità
                payout_status = status_raw.lower() if status_raw else None
                is_paid = (magellano_status == 'magellano_sent')
                
                # Estrai eventuali ID Meta se le colonne esistono
                meta_campaign_id = None
                meta_adset_id = None
                meta_ad_id = None
                if campaign_id_col:
                    raw = row.get(campaign_id_col, None)
                    if raw is not None and not pd.isna(raw):
                        meta_campaign_id = str(raw).strip()
                if adset_id_col:
                    raw = row.get(adset_id_col, None)
                    if raw is not None and not pd.isna(raw):
                        meta_adset_id = str(raw).strip()
                if ad_id_col:
                    raw = row.get(ad_id_col, None)
                    if raw is not None and not pd.isna(raw):
                        meta_ad_id = str(raw).strip()
                
                leads.append({
                    'magellano_id': ext_user_id,  # ID da Magellano (senza prefisso)
                    'external_user_id': f"MAG-{ext_user_id}",  # ID interno con prefisso (usato per Ulixe)
                    'first_name': str(row.get('First name', '')).strip(),
                    'last_name': str(row.get('Last name', '')).strip(),
                    'email': email,
                    'phone': str(row.get('Telephone', '')).strip() if not pd.isna(row.get('Telephone')) else None,
                    'brand': str(row.get('gruppocepu_serviziobrand', '')).strip() if not pd.isna(row.get('gruppocepu_serviziobrand')) else None,
                    'msg_id': str(row.get('gruppocepu_idmessaggio', '')).strip() if not pd.isna(row.get('gruppocepu_idmessaggio')) else None,
                    'form_id': str(row.get('gruppocepu_formid', '')).strip() if not pd.isna(row.get('gruppocepu_formid')) else None,
                    'source': str(row.get('Source', '')).strip() if not pd.isna(row.get('Source')) else None,
                    'campaign_name': str(row.get('Campaign', '')).strip().strip(),
                    'magellano_campaign_id': str(campaign_id),
                    # Stato Magellano: originale, normalizzato e categoria
                    'magellano_status_raw': status_raw,  # Stato originale esatto
                    'magellano_status': magellano_status,  # Stato normalizzato
                    'magellano_status_category': magellano_status_category,  # Categoria normalizzata
                    # Payout status (deprecated, mantenuto per retrocompatibilità) - contiene lo stato originale
                    'payout_status': payout_status,
                    # Stato originale non normalizzato (per retrocompatibilità)
                    'status_raw': status_raw,
                    'is_paid': is_paid,
                    # Facebook/Meta fields from Magellano
                    'facebook_ad_name': str(row.get('facebook_ad_name', '')).strip() if not pd.isna(row.get('facebook_ad_name', '')) else None,
                    'facebook_ad_set': str(row.get('facebook_ad_set', '')).strip() if not pd.isna(row.get('facebook_ad_set', '')) else None,
                    'facebook_campaign_name': str(row.get('facebook_campaign_name', '')).strip() if not pd.isna(row.get('facebook_campaign_name', '')) else None,
                    'facebook_id': str(row.get('facebook_id', '')).strip() if not pd.isna(row.get('facebook_id', '')) else None,  # ID utente Facebook
                    'facebook_piattaforma': str(row.get('facebook_piattaforma', '')).strip() if not pd.isna(row.get('facebook_piattaforma', '')) else None,
                    # ID Meta (se esportati da Magellano)
                    'meta_campaign_id': meta_campaign_id,
                    'meta_adset_id': meta_adset_id,
                    'meta_ad_id': meta_ad_id,
                    # Data di iscrizione Magellano
                    'magellano_subscr_date': magellano_subscr_date,
                    # NON impostare status_category di default - verrà determinato in base a magellano_status
                    # 'status_category': 'in_lavorazione'  # Rimosso - non più default
                })
            
            return leads

        except Exception as e:
            logger.error(f"Excel processing failed: {e}")
            return []
