import json
import logging
import os
import zipfile
import tempfile
import shutil
from datetime import datetime, date, timedelta
import requests
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from playwright.sync_api import sync_playwright
import subprocess
import sys
import random
import time
import re
import argparse
from fake_useragent import UserAgent
from gspread_formatting import CellFormat, Color, format_cell_range
from gspread.utils import rowcol_to_a1
from concurrent.futures import ThreadPoolExecutor, as_completed
from gspread.exceptions import APIError

# ===============================================
# COSTANTI - Configurazione Google Sheets
# ===============================================
COLUMNS_WITH_LABELS = ['First name', 'Email', 'Telephone', 'ragione_sociale']
COLUMN_INDICES = [7, 11, 12, 32]  # Indici delle colonne: H, L, M, AG
SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fce6fPnfohy0bBJ1g3FIeYL-BkJ92EgHJ2HbMpDaxdM/edit#gid=0"
SHEET_NAME = "lead"
HEADER_ROW = 3
CREDENTIALS_FILE = "credentials.json"  # Percorso relativo alla directory principale

# Costanti per l'automazione buoni-pasto
SPREADSHEET_ID = '1Fce6fPnfohy0bBJ1g3FIeYL-BkJ92EgHJ2HbMpDaxdM'
LANDING_PAGE_URL = 'https://toppartners.it/landing/novita-buoni-pasto-2/?utm_term=cta&utm_source=newsletter_ext&utm_medium=email&utm_campaign=ottobre_2025_triboo'
IFRAME_SELECTOR = 'iframe'  # Il selettore dell'iframe rimane generico
WAIT_BEFORE_NEXT_MIN = 1
WAIT_BEFORE_NEXT_MAX = 2
MAX_WORKERS = 1
HEADLESS_MODE = True  # Cambia a False per usare la GUI

field_mappings = {
    'email': {'sheet_column': 'email', 'locator': '#txtEmail'},
    'telephone': {'sheet_column': 'telephone', 'locator': '#txtPhone'},
    'first_name': {'sheet_column': 'first_name', 'locator': '#txtFirstName'},
    'last_name': {'sheet_column': 'last_name', 'locator': '#txtLastName'},
    'company_name': {'sheet_column': 'ragione_sociale', 'locator': '#txtBusinessName'},
}

# ===============================================

# Configurazione del logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)

def parse_arguments():
    """
    Parsing degli argomenti da riga di comando
    """
    parser = argparse.ArgumentParser(
        description='Automazione Magellano: download campagne, upload su Google Sheet, invio dati a landing page.\n\nModalità disponibili:\n  --sheet   Scarica dati da Magellano e carica su Google Sheet\n  --lp      Invia dati dal Google Sheet alla landing page\n  (default: entrambe)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi di utilizzo:
  python magellano_automation.py                    # Tutte le campagne, data automatica
  python magellano_automation.py --635              # Solo campagna 635
  python magellano_automation.py --669 --635 --723  # Campagne 669, 635 e 723
  python magellano_automation.py --start-date 2025-07-01 --end-date 2025-07-15
  python magellano_automation.py --635 --start-date 2025-07-01 --end-date 2025-07-15
  python magellano_automation.py --sheet            # Solo download Magellano + upload sheet
  python magellano_automation.py --lp               # Solo invio dati da sheet a LP
  python magellano_automation.py --lp --worker 3    # Invio dati con 3 worker paralleli
  python magellano_automation.py --help             # Mostra questo help
        """
    )
    
    # Argomenti per le campagne
    parser.add_argument('--635', action='store_true', dest='campaign_635', help='Processa campagna 635')
    parser.add_argument('--669', action='store_true', dest='campaign_669', help='Processa campagna 669')
    parser.add_argument('--723', action='store_true', dest='campaign_723', help='Processa campagna 723')
    
    # Argomenti per le date
    parser.add_argument('--start-date', type=str, help='Data di inizio (formato: YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='Data di fine (formato: YYYY-MM-DD)')
    
    # Modalità operative
    parser.add_argument('--sheet', action='store_true', help='Esegui solo download Magellano + upload su Google Sheet')
    parser.add_argument('--lp', action='store_true', help='Esegui solo invio dati da Google Sheet a landing page')
    
    # Argomenti opzionali
    parser.add_argument('--no-buoni-pasto', action='store_true', help='(DEPRECATO, usa --lp)')
    parser.add_argument('--headless', action='store_true', default=True, help='Modalità headless (default: True)')
    parser.add_argument('--gui', action='store_true', help='Modalità GUI (disabilita headless)')
    parser.add_argument('--worker', type=int, default=1, help='Numero di worker per l\'automazione buoni-pasto (default: 1)')
    
    return parser.parse_args()

def validate_date(date_string):
    """
    Valida il formato della data
    """
    try:
        return datetime.strptime(date_string, '%Y-%m-%d').date()
    except ValueError:
        raise argparse.ArgumentTypeError(f'Data non valida: {date_string}. Usa il formato YYYY-MM-DD')

def get_campaigns_from_args(args):
    """
    Determina le campagne da processare basandosi sugli argomenti
    """
    campaigns = []
    
    if args.campaign_635:
        campaigns.append(635)
    if args.campaign_669:
        campaigns.append(669)
    if args.campaign_723:
        campaigns.append(723)
    
    # Se non è specificata nessuna campagna, usa tutte
    if not campaigns:
        campaigns = [635, 669, 723]
    
    return campaigns

def get_date_range_from_args(args):
    """
    Determina il range di date da processare
    """
    # Se l'utente specifica le date, usale
    if args.start_date and args.end_date:
        start_date = validate_date(args.start_date)
        end_date = validate_date(args.end_date)
        if start_date > end_date:
            raise ValueError("La data di inizio deve essere precedente alla data di fine")
        return start_date, end_date
    # Logica automatica in base al giorno della settimana
    today = datetime.now().date()
    weekday = today.weekday()  # 0=lun, 1=mar, ..., 6=dom
    if weekday in [5, 6]:  # Sabato o Domenica
        logging.info("Oggi è sabato o domenica: nessuna operazione da eseguire.")
        sys.exit(0)
    elif weekday == 0:  # Lunedì
        # Solo venerdì (3 giorni fa)
        start_date = today - timedelta(days=3)
        end_date = start_date
        logging.info(f"Lunedì: raccolgo dati di venerdì: {start_date}")
        return start_date, end_date
    elif weekday == 1:  # Martedì
        # Sabato (3 giorni fa), Domenica (2 giorni fa), Lunedì (1 giorno fa)
        start_date = today - timedelta(days=3)
        end_date = today - timedelta(days=1)
        logging.info(f"Martedì: raccolgo dati da {start_date} a {end_date}")
        return start_date, end_date
    else:
        # Mercoledì-Venerdì: solo ieri
        start_date = today - timedelta(days=1)
        end_date = start_date
        logging.info(f"Giorno feriale: raccolgo dati di ieri: {start_date}")
        return start_date, end_date

def split_first_name(full_name):
    """
    Divide il campo "First name" in first_name e last_name.
    Se c'è almeno uno spazio, il primo elemento diventa first_name e il resto last_name.
    Se non c'è spazio, last_name viene impostato a "-".
    """
    if not isinstance(full_name, str) or not full_name.strip():
        return ("-", "-")
    parts = full_name.strip().split(" ", 1)
    if len(parts) == 1:
        return (parts[0], "-")
    else:
        return (parts[0], parts[1])

def generate_password():
    """
    Genera la password dinamica nel formato "ggmmaaT-Direct"
    Esempio: oggi 02/07/2025 -> "02072025T-Direct"
    """
    today = date.today()
    password = today.strftime("%d%m%Y") + "T-Direct"
    logging.info(f"Password generata: {password}")
    return password

def download_campaign_file(playwright, campaign_url, campaign_number, start_date, end_date):
    """
    Scarica il file ZIP dalla campagna specifica di Magellano
    """
    logging.info(f"Inizio download file dalla campagna {campaign_number} per il periodo {start_date} - {end_date}")
    
    browser = playwright.chromium.launch(
        headless=False,  # Cambia in True per produzione
        args=[
            '--disable-gpu',
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-extensions',
            '--disable-popup-blocking',
            '--disable-notifications'
        ]
    )
    
    context = browser.new_context(
        viewport={'width': 1400, 'height': 900},
        accept_downloads=True,
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    )
    
    page = context.new_page()
    
    # Nome file custom per export
    start_date_str = start_date.strftime('%d%m%Y')
    end_date_str = end_date.strftime('%d%m%Y')
    export_filename = f"top-partners-{start_date_str}-{end_date_str}-campaign-{campaign_number}"
    export_filename_xls = f"{export_filename}.xls"
    download_info = {"file": None}
    
    # Gestione dialog per nome file e alert
    def handle_dialog(dialog):
        logging.info(f"🔔 Dialog rilevato: {dialog.type} - {dialog.message}")
        if dialog.type == "prompt":
            logging.info(f"📝 Inserisco nome file custom: {export_filename}")
            dialog.accept(export_filename)
        elif dialog.type == "alert":
            dialog.accept()
        else:
            dialog.accept()
    page.on("dialog", handle_dialog)
    
    # Gestione download
    def handle_download(download):
        logging.info(f"📥 Download rilevato: {download.suggested_filename}")
        download_path = f"./downloads/{download.suggested_filename}"
        os.makedirs("./downloads", exist_ok=True)
        download.save_as(download_path)
        download_info["file"] = download_path
        logging.info(f"✅ File salvato: {download_path}")
    page.on("download", handle_download)
    
    try:
        # Login a Magellano
        logging.info("1️⃣ Accesso alla pagina di login")
        page.goto("https://magellano.ai/admin/index.php?menuNode=15.04&module=importPanelPublisher&method=main")
        page.fill("#weblib_username", "giorgio")
        page.fill("#weblib_password", "Magellano2025!")
        page.click("a[href*='form_login'].btn-primary")
        page.wait_for_load_state('networkidle')
        logging.info("✅ Login completato")
        
        # Step 1: Click su Campaigns nel menu principale
        logging.info("2️⃣ Click su menu Campaigns")
        page.click('a[title=""] i.fa-users')  # Menu principale Campaigns
        page.wait_for_timeout(1000)
        
        # Click su Campaigns nel sottomenu
        page.click('a[href*="menuNode=05.01&module=listCoregs&method=main"]')
        page.wait_for_load_state('networkidle')
        logging.info("✅ Navigazione a Campaigns completata")
        
        # Step 2: Click sul collapse menu (filtri)
        logging.info("3️⃣ Apertura filtri")
        page.click('a[data-rel="collapse"] i.fa-plus')
        page.wait_for_timeout(1000)
        logging.info("✅ Filtri aperti")
        
        # Step 3: Ricerca campagna specifica
        logging.info(f"4️⃣ Ricerca campagna {campaign_number}")
        
        # Metodo 1: Prova con JavaScript diretto per select2
        try:
            page.evaluate(f"""
                // Trova il select2 e aprilo
                $('.select2-choices').click();
                setTimeout(function() {{
                    // Digita nel campo di ricerca
                    $('.select2-input').val('{campaign_number}').trigger('input').trigger('keyup');
                }}, 500);
            """)
            page.wait_for_timeout(1500)
            
            # Clicca sul risultato
            page.click(f'.select2-result-label:has-text("{campaign_number}")', timeout=3000)
            logging.info("✅ Selezione con JavaScript riuscita")
            
        except Exception as e:
            logging.info(f"Metodo JavaScript fallito: {e}, provo metodo alternativo...")
            
            # Metodo 2: Approccio manuale
            page.click('.select2-choices')
            page.wait_for_timeout(1000)
            
            # Trova il campo input e digita
            search_input = page.locator('.select2-input').first
            search_input.click()
            search_input.fill(str(campaign_number))
            page.wait_for_timeout(1000)
            
            # Premi Enter
            search_input.press('Enter')
            page.wait_for_timeout(1000)
            
            # Se non funziona, clicca sul risultato
            try:
                page.click(f'.select2-result:has-text("{campaign_number}")')
            except:
                page.click(f'text={campaign_number}')
        
        page.wait_for_timeout(500)
        
        # Click su Apply filters
        page.click('a.btn-success:has-text("Apply filters")')
        page.wait_for_load_state('networkidle')
        logging.info(f"✅ Filtro campagna {campaign_number} applicato")
        
        # Step 4: Verifica presenza campagna e click su Users
        logging.info("5️⃣ Click su icona Users della campagna")
        # Dato che abbiamo filtrato per la campagna, dovrebbe esserci solo una riga
        # Clicca sul button Users corretto
        users_button = page.locator('button[data-original-title="Users"] i.fa-users').first
        users_button.click()
        page.wait_for_load_state('networkidle')
        logging.info("✅ Navigazione a Users completata")
        
        # Step 5: Selezione data di inizio
        logging.info(f"6️⃣ Selezione prima data ({start_date.day})")
        
        # Click sul primo campo data
        page.locator('.input-group-addon .glyphicon-calendar').first.click()
        page.wait_for_timeout(1000)
        
        # Seleziona la data di inizio nel calendario visibile
        try:
            page.locator('.datepicker:visible td.day').filter(has_text=str(start_date.day)).first.click()
            logging.info(f"✅ Prima data selezionata: {start_date.day}")
        except Exception as e:
            logging.info(f"Tentativo alternativo: {e}")
            # Fallback: usa JavaScript
            page.evaluate(f"""
                const calendar = document.querySelector('.datepicker:visible');
                if (calendar) {{
                    const days = calendar.querySelectorAll('td.day');
                    for (let day of days) {{
                        if (day.textContent.trim() === '{start_date.day}' && !day.classList.contains('old') && !day.classList.contains('new')) {{
                            day.click();
                            break;
                        }}
                    }}
                }}
            """)
            logging.info(f"✅ Prima data selezionata (JavaScript): {start_date.day}")
        
        page.wait_for_timeout(500)
        
        # Step 6: Selezione data di fine
        logging.info(f"7️⃣ Selezione seconda data ({end_date.day})")
        # Click sul secondo campo data
        page.locator('.input-group-addon .glyphicon-calendar').nth(1).click()
        page.wait_for_timeout(1000)
        
        # Seleziona la data di fine nel calendario visibile
        try:
            # Prima prova: clicca direttamente sul giorno visibile
            page.locator('.datepicker:visible td.day').filter(has_text=str(end_date.day)).first.click()
            logging.info(f"✅ Seconda data selezionata: {end_date.day}")
        except Exception as e:
            logging.info(f"Tentativo alternativo: {e}")
            # Fallback: usa JavaScript per cliccare
            page.evaluate(f"""
                const calendar = document.querySelector('.datepicker:visible');
                if (calendar) {{
                    const days = calendar.querySelectorAll('td.day');
                    for (let day of days) {{
                        if (day.textContent.trim() === '{end_date.day}' && !day.classList.contains('old') && !day.classList.contains('new')) {{
                            day.click();
                            break;
                        }}
                    }}
                }}
            """)
            logging.info(f"✅ Seconda data selezionata (JavaScript): {end_date.day}")
        
        page.wait_for_timeout(500)
        
        # Step 7: Selezione status "Sent"
        logging.info("8️⃣ Selezione status 'Sent'")
        
        # Approccio con select2 per il campo "Sent to customer"
        try:
            # Metodo 1: Click sul select2 del campo "Sent to customer"
            page.click('#s2id_filters_sent .select2-choice')
            page.wait_for_timeout(1000)
            
            # Seleziona l'opzione "Sent (accept from WS or by email)"
            page.click('.select2-results li:has-text("Sent (accept from WS or by email)")')
            logging.info("✅ Status 'Sent' selezionato")
            
        except Exception as e:
            logging.info(f"Tentativo alternativo per select2: {e}")
            # Metodo 2: JavaScript diretto per impostare il valore
            page.evaluate("""
                // Imposta il valore del select nascosto
                const select = document.getElementById('filters_sent');
                if (select) {
                    select.value = '1'; // Valore per "Sent (accept from WS or by email)"
                    
                    // Trigger dell'evento change per select2
                    $(select).trigger('change');
                    
                    // Aggiorna il display di select2
                    $('#s2id_filters_sent .select2-chosen').text('Sent (accept from WS or by email)');
                }
            """)
            logging.info("✅ Status 'Sent' selezionato (JavaScript)")
        
        page.wait_for_timeout(500)
        
        # Step 8: Apply filters
        logging.info("9️⃣ Applicazione filtri finali")
        page.click('a.btn-success:has-text("Apply filters")')
        page.wait_for_load_state('networkidle')
        logging.info("✅ Filtri applicati")
        
        # Step 9: Export
        logging.info("🔟 Avvio Export")
        export_button = page.locator('a.btn-primary:has-text("Export")')
        export_button.click()
        
        # Attendi i dialog (prompt e alert) e la generazione del file
        page.wait_for_timeout(3000)
        
        # Naviga su Export > Exports List
        logging.info("🔄 Navigazione su Export > Exports List")
        page.click('a[title=""] i.fa-database')  # Menu Export
        page.wait_for_timeout(1000)
        page.click('a[href*="menuNode=10.07&module=listExportsList&method=main"]')
        page.wait_for_load_state('networkidle')
        
        # Cerca la riga con il nome file e aspetta che lo status sia "completed"
        logging.info(f"🔍 Cerco la riga con filename: {export_filename_xls} e status 'completed'")
        found = False
        max_attempts = 30  # Aumento il numero di tentativi per aspettare più tempo
        refresh_attempts = 0
        max_refresh_attempts = 3
        
        for attempt in range(max_attempts):
            rows = page.locator(f'table#table-basic tr').all()
            for row in rows:
                row_text = row.inner_text()
                if export_filename_xls in row_text and "completed" in row_text.lower():
                    found = True
                    logging.info(f"✅ File {export_filename_xls} trovato con status 'completed'")
                    # Clicca il pulsante download nella riga
                    download_btn = row.locator('button[data-original-title="Download"]')
                    download_btn.click()
                    logging.info(f"✅ Download avviato per {export_filename_xls}")
                    break
            if found:
                break
                
            # NUOVO: Refresh della pagina dopo 5 tentativi
            if attempt > 0 and attempt % 5 == 0 and refresh_attempts < max_refresh_attempts:
                logging.info(f"🔄 Tentativo {attempt + 1}: Refresh della pagina dopo 5 tentativi")
                page.reload()
                page.wait_for_load_state('networkidle')
                refresh_attempts += 1
                logging.info(f"✅ Pagina refreshata (tentativo {refresh_attempts}/{max_refresh_attempts})")
                
            logging.info(f"⏳ Tentativo {attempt + 1}/{max_attempts}: File non ancora completato, attendo...")
            page.wait_for_timeout(2000)  # Attendi 2s e riprova
        
        if not found:
            logging.error(f"❌ File {export_filename_xls} non trovato o non completato in Export List dopo {max_attempts} tentativi")
            return None
        
        # Attendi il download
        page.wait_for_timeout(5000)
        if download_info["file"]:
            logging.info(f"✅ Download completato: {download_info['file']}")
            return download_info["file"]
        else:
            logging.error("❌ Nessun download rilevato")
            return None
        
    except Exception as e:
        logging.error(f"❌ Errore durante il download: {str(e)}")
        return None
    finally:
        browser.close()

def extract_zip_file(zip_path, extract_to):
    """
    Estrae il file ZIP e cerca il file XLS
    """
    logging.info(f"Estrazione del file ZIP: {zip_path}")
    
    try:
        # Genera la password per il file ZIP (stesso formato della password di login)
        password = generate_password()
        logging.info(f"Tentativo estrazione con password: {password}")
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to, pwd=password.encode('utf-8'))
        
        # Cerca il file XLS
        xls_files = []
        for root, dirs, files in os.walk(extract_to):
            for file in files:
                if file.endswith('.xls') or file.endswith('.xlsx'):
                    xls_files.append(os.path.join(root, file))
        
        if not xls_files:
            logging.error("Nessun file XLS trovato nell'archivio ZIP")
            return None
        
        # Prendi il primo file XLS trovato
        xls_file = xls_files[0]
        logging.info(f"File XLS trovato: {xls_file}")
        return xls_file
        
    except Exception as e:
        logging.error(f"Errore durante l'estrazione: {str(e)}")
        return None

def process_excel_and_upload_to_sheets(xls_file):
    """
    Processa il file Excel e carica i dati su Google Sheets
    """
    logging.info("Inizio processamento file Excel e upload su Google Sheets")
    
    try:
        # Legge il file Excel
        logging.info(f"Lettura del file Excel: {xls_file}")
        try:
            df = pd.read_excel(xls_file)
            df_extracted = df[COLUMNS_WITH_LABELS]
            logging.info("File letto con header etichettati")
        except KeyError:
            logging.info("Le colonne non sono etichettate, utilizzo gli indici per l'estrazione...")
            df = pd.read_excel(xls_file, header=None)
            df_extracted = df.iloc[:, COLUMN_INDICES]
            df_extracted.columns = COLUMNS_WITH_LABELS
        
        logging.info("Estrazione colonne completata.")
        
        # Processa la colonna "First name" per separare nome e cognome
        logging.info("Separazione di 'First name' in 'first_name' e 'last_name'.")
        df_extracted = df_extracted.copy()  # Evita il SettingWithCopyWarning
        df_extracted[['first_name', 'last_name']] = df_extracted['First name'].apply(
            lambda x: pd.Series(split_first_name(x))
        )
        
        # Prepara il DataFrame finale
        df_final = df_extracted[['Email', 'first_name', 'last_name', 'Telephone', 'ragione_sociale']]
        df_final.columns = ['email', 'first_name', 'last_name', 'telephone', 'ragione_sociale']
        logging.info(f"Preparazione dei dati completata. Numero di record: {len(df_final)}")
        
        # Autenticazione Google Sheets
        logging.info("Autenticazione su Google Sheets in corso...")
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        client = gspread.authorize(creds)
        
        # Apre il Google Sheet
        logging.info(f"Apertura del Google Sheet: {SHEET_URL}")
        sheet = client.open_by_url(SHEET_URL)
        worksheet = sheet.worksheet(SHEET_NAME)
        
        # Trova la prima riga vuota
        existing_data = worksheet.get_all_values()
        row_to_start = len(existing_data) + 1 if len(existing_data) >= HEADER_ROW else HEADER_ROW + 1
        logging.info(f"Inizio dell'inserimento dati a partire dalla riga {row_to_start}.")
        
        # Inserisce i dati
        data_to_insert = df_final.values.tolist()
        for row in data_to_insert:
            worksheet.append_row(row)
        
        logging.info("Dati inseriti con successo nel Google Sheet.")
        return True
        
    except Exception as e:
        logging.error(f"Errore durante il processamento: {str(e)}")
        return False

def cleanup_files(zip_path, extract_dir):
    """
    Elimina i file temporanei
    """
    logging.info("Pulizia file temporanei")
    
    try:
        if zip_path and os.path.exists(zip_path):
            os.remove(zip_path)
            logging.info(f"File ZIP eliminato: {zip_path}")
        
        if extract_dir and os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
            logging.info(f"Directory di estrazione eliminata: {extract_dir}")
            
    except Exception as e:
        logging.error(f"Errore durante la pulizia: {str(e)}")

# ===============================================
# FUNZIONI PER L'AUTOMAZIONE BUONI-PASTO
# ===============================================

def get_column_names(sheet):
    logging.info("Recupero delle intestazioni dalla riga 3...")
    headers = sheet.row_values(3)  # Rileggiamo direttamente per avere intestazioni aggiornate
    logging.debug(f"Intestazioni recuperate: {headers}")
    return headers

def find_rows_to_upload(sheet):
    logging.info("Cerco tutte le righe da caricare...")
    data = sheet.get_all_values()  # Ricarica i dati completamente ogni volta che viene chiamata la funzione
    logging.debug(f"Dati caricati da Google Sheets: {data}")
    rows_to_upload = []
    headers = data[2]
    status_col_index = headers.index("status")

    for idx, row in enumerate(data[3:], start=4):
        logging.debug(f"Verifica della riga {idx}: {row}")
        if len(row) > status_col_index and row[status_col_index] == "":
            rows_to_upload.append(idx)

    logging.info(f"Righe da processare trovate: {rows_to_upload}")
    return rows_to_upload

def handle_overlays(page):
    logging.info("Gestione degli overlay...")
    
    # Attesa per il caricamento completo della pagina
    time.sleep(3)
    
    # Lista di possibili selettori per i pulsanti dei cookie
    cookie_selectors = [
        'button.iubenda-cs-accept-btn.iubenda-cs-btn-primary',  # Pulsante accetta Iubenda
        'button[id*="accept"]',  # Pulsanti con "accept" nell'ID
        'button[class*="accept"]',  # Pulsanti con "accept" nella classe
        'button:has-text("Accetta")',  # Pulsanti con testo "Accetta"
        'button:has-text("Accept")',  # Pulsanti con testo "Accept"
        'button:has-text("Continua")',  # Pulsanti con testo "Continua"
        'a:has-text("Continua senza accettare")',  # Link "Continua senza accettare"
        '[class*="cookie"] button',  # Qualsiasi pulsante dentro elementi con "cookie" nella classe
        '[id*="cookie"] button',  # Qualsiasi pulsante dentro elementi con "cookie" nell'ID
        'button[class*="iubenda"]',  # Pulsanti Iubenda generici
        '[class*="iubenda"] button',  # Pulsanti dentro elementi Iubenda
        '[id*="iubenda"] button'  # Pulsanti dentro elementi con ID Iubenda
    ]
    
    # Prova prima con il click JavaScript forzato
    for selector in cookie_selectors:
        try:
            logging.info(f"Tentativo di click JavaScript per selettore: {selector}")
            
            # Usa JavaScript per cercare e cliccare l'elemento, anche se non è visibile
            result = page.evaluate(f"""
                const element = document.querySelector('{selector}');
                if (element) {{
                    console.log('Elemento trovato:', element);
                    element.click();
                    return true;
                }}
                return false;
            """)
            
            if result:
                logging.info(f"Banner cookie gestito con successo via JavaScript usando selettore: {selector}")
                time.sleep(3)  # Attesa dopo il click
                return
            else:
                logging.debug(f"Elemento non trovato nel DOM per selettore: {selector}")
        except Exception as e:
            logging.debug(f"Errore JavaScript con selettore {selector}: {e}")
            continue
    
    # Se JavaScript non funziona, prova con il metodo Playwright normale
    for selector in cookie_selectors:
        try:
            logging.info(f"Tentativo di click Playwright per selettore: {selector}")
            cookie_element = page.locator(selector).first
            
            # Controlla se l'elemento esiste nel DOM
            if cookie_element.count() > 0:
                # Forza il click anche se non è visibile
                cookie_element.click(force=True)
                logging.info(f"Banner cookie gestito con successo via Playwright (force=True) usando selettore: {selector}")
                time.sleep(3)  # Attesa dopo il click
                return
            else:
                logging.debug(f"Elemento non presente nel DOM per selettore: {selector}")
        except Exception as e:
            logging.debug(f"Errore Playwright con selettore {selector}: {e}")
            continue
    
    # Come ultima risorsa, prova a cliccare qualsiasi elemento che contenga parole chiave
    logging.info("Tentativo di click su qualsiasi elemento con parole chiave cookie...")
    fallback_result = page.evaluate("""
        const keywords = ['cookie', 'accept', 'accetta', 'continua', 'iubenda'];
        const allElements = document.querySelectorAll('*');
        
        for (let element of allElements) {
            const text = element.textContent ? element.textContent.toLowerCase() : '';
            const className = element.className ? element.className.toLowerCase() : '';
            const id = element.id ? element.id.toLowerCase() : '';
            
            for (let keyword of keywords) {
                if (text.includes(keyword) || className.includes(keyword) || id.includes(keyword)) {
                    if (element.tagName === 'BUTTON' || element.tagName === 'A') {
                        console.log('Elemento fallback trovato:', element);
                        element.click();
                        return true;
                    }
                }
            }
        }
        return false;
    """)
    
    if fallback_result:
        logging.info("Banner cookie gestito con successo via ricerca fallback")
        time.sleep(3)
    else:
        logging.info("Nessun banner cookie trovato con tutti i metodi disponibili. Continuando...")
    
    time.sleep(1)

def map_data_to_form(page, data_dict):
    logging.info("Mappatura dei dati nel form...")
    handle_overlays(page)

    # Tentativo più robusto per trovare l'iframe in modalità headless
    iframe_page = None
    for attempt in range(3):
        try:
            logging.info(f"Tentativo {attempt + 1} di trovare l'iframe...")
            
            # Prova prima con iframe visibile, poi con qualsiasi iframe
            iframe_selectors = [
                'iframe.the_frame:visible',  # Iframe visibile con classe the_frame
                'iframe:visible',            # Qualsiasi iframe visibile
                'iframe.the_frame',          # Iframe con classe the_frame (anche nascosto)
                'iframe'                     # Qualsiasi iframe
            ]
            
            for selector in iframe_selectors:
                try:
                    logging.info(f"Tentativo con selettore: {selector}")
                    iframe_element = page.locator(selector).first
                    iframe_element.wait_for(timeout=5000)
                    logging.info(f"Iframe trovato con selettore: {selector}")
                    iframe_page = page.frame_locator(selector).first
                    logging.info("Passaggio all'iframe riuscito.")
                    break
                except Exception as e:
                    logging.debug(f"Selettore {selector} fallito: {e}")
                    continue
            
            if iframe_page:
                break
                
        except Exception as e:
            logging.warning(f"Tentativo {attempt + 1} fallito per l'iframe: {e}")
            if attempt < 2:
                time.sleep(2)
                page.reload()
                time.sleep(3)
    
    if iframe_page is None:
        logging.error("Impossibile trovare l'iframe dopo 3 tentativi")
        return False

    # Compila i campi del form
    for field_key, field_info in field_mappings.items():
        try:
            locator = field_info['locator']
            sheet_column = field_info['sheet_column']
            field_value = data_dict.get(sheet_column, '')

            logging.debug(f"Mappatura del campo '{field_key}' con valore '{field_value}'")

            if field_key == 'email' and not is_valid_email(field_value):
                logging.warning(f"Email non valida: {field_value}")
                continue

            logging.info(f"Tentativo di mappare il campo '{field_key}'...")
            # Localizza l'elemento nell'iframe
            element = iframe_page.locator(locator)
            element.wait_for(timeout=10000)
            
            # Scroll verso l'elemento per assicurarsi che sia visibile
            element.scroll_into_view_if_needed()
            time.sleep(1)
            
            # Rimuove readonly e disabled se presenti
            page.evaluate(f"""
                const iframe = document.querySelector('iframe');
                if (iframe && iframe.contentDocument) {{
                    const element = iframe.contentDocument.querySelector('{locator}');
                    if (element) {{
                        element.removeAttribute('readonly');
                        element.removeAttribute('disabled');
                    }}
                }}
            """)
            
            element.click()
            element.clear()
            element.fill(field_value)
            logging.info(f"Campo '{field_key}' compilato con successo.")
        except Exception as e:
            logging.error(f"Errore con il campo '{field_key}': {e}")
            return False

    # I checkbox dei disclaimer NON devono essere cliccati
    # Il primo disclaimer è già selezionato automaticamente (disclaimer_1 con value="1" è hidden)
    # Gli altri checkbox (disclaimer_2 e disclaimer_4) rimangono deselezionati
    logging.info("Checkbox dei disclaimer lasciati deselezionati come richiesto")

    return True

def is_valid_email(email):
    logging.debug(f"Verifica validità email: {email}")
    valid = re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None
    logging.debug(f"Verifica email '{email}': {'valida' if valid else 'non valida'}")
    return valid

def update_sheet(sheet, row_idx, success):
    logging.info(f"Aggiornamento del foglio per la riga {row_idx}...")
    try:
        status_col = sheet.find('status').col
        timestamp_col = sheet.find('timestamp').col
        current_time = datetime.now().strftime('%Y-%m-%d')

        if success:
            logging.info(f"Aggiornamento stato della riga {row_idx} a 'X' e timestamp a '{current_time}'...")
            sheet.update_cell(row_idx, status_col, 'X')
            sheet.update_cell(row_idx, timestamp_col, current_time)
            green_format = CellFormat(backgroundColor=Color(0.8, 0.94, 0.8))
        else:
            logging.info(f"Aggiornamento stato della riga {row_idx} a 'fallito'...")
            sheet.update_cell(row_idx, status_col, 'ERROR')
            yellow_format = CellFormat(backgroundColor=Color(1.0, 1.0, 0.6))
            
        num_cols = len(get_column_names(sheet))
        cell_range = f"{rowcol_to_a1(row_idx, 1)}:{rowcol_to_a1(row_idx, num_cols)}"
        logging.info(f"Formattazione della riga {row_idx} in corso...")
        format_cell_range(sheet, cell_range, green_format if success else yellow_format)
        logging.info(f"Formato della riga {row_idx} aggiornato con successo.")
    except Exception as e:
        logging.error(f"Errore durante l'aggiornamento della riga {row_idx}: {e}")

def configure_browser_options(ua):
    """Configura le opzioni del browser in base alla modalità (headless o GUI)"""
    launch_options = {
        'args': [
            '--disable-cache',
            '--disk-cache-size=0',
            '--disable-blink-features=AutomationControlled',
            '--disable-application-cache',
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-web-security',
            '--allow-running-insecure-content',
            '--disable-features=VizDisplayCompositor',
            '--window-size=1920,1080',
            '--start-maximized',
            '--force-device-scale-factor=1'
        ]
    }
    
    if HEADLESS_MODE:
        launch_options['headless'] = True
        logging.info("Modalità headless attivata")
    else:
        launch_options['headless'] = False
        logging.info("Modalità GUI attivata")
    
    context_options = {
        'user_agent': ua.random,
        'viewport': {'width': 1920, 'height': 1080},
        'ignore_https_errors': True,
        'java_script_enabled': True,
        'device_scale_factor': 1.0,
        'is_mobile': False,
        'has_touch': False,
        'screen': {'width': 1920, 'height': 1080}
    }
    
    return launch_options, context_options

def process_entry(row_idx, data_dict, sheet):
    logging.info(f"Inizio elaborazione entry per la riga {row_idx}...")
    ua = UserAgent()
    launch_options, context_options = configure_browser_options(ua)

    playwright = None
    browser = None
    context = None
    
    try:
        # NUOVA SESSIONE COMPLETAMENTE PULITA PER OGNI RIGA
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(**context_options)
        page = context.new_page()
        
        # Imposta esplicitamente le dimensioni della finestra
        page.set_viewport_size({"width": 1920, "height": 1080})
        
        logging.info(f"Apertura URL: {LANDING_PAGE_URL}")
        # Semplifichiamo il caricamento - se si carica correttamente come dici
        page.goto(LANDING_PAGE_URL, wait_until='domcontentloaded', timeout=30000)
        logging.info("Pagina caricata con successo.")
        
        time.sleep(3 if HEADLESS_MODE else 2)  # Più tempo per headless
        
        # Scroll per assicurarsi che la pagina sia completamente caricata
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)
        
        # Attesa aggiuntiva per il caricamento completo in headless
        if HEADLESS_MODE:
            page.wait_for_selector("body", timeout=10000)
        
        if not map_data_to_form(page, data_dict):
            logging.error("Errore nella mappatura dei dati al form.")
            update_sheet(sheet, row_idx, False)
            return False

        try:
            logging.info("Tentativo di cliccare il pulsante di invio...")
            time.sleep(7 if HEADLESS_MODE else 5)  # Più tempo per headless
            
            # Trova l'iframe per accedere al pulsante di submit
            iframe_selectors = [
                'iframe.the_frame:visible',  # Iframe visibile con classe the_frame
                'iframe:visible',            # Qualsiasi iframe visibile
                'iframe.the_frame',          # Iframe con classe the_frame (anche nascosto)
                'iframe'                     # Qualsiasi iframe
            ]
            
            iframe_page = None
            for selector in iframe_selectors:
                try:
                    logging.info(f"Tentativo submit con selettore: {selector}")
                    iframe_page = page.frame_locator(selector).first
                    submit_button = iframe_page.locator('#submit_btn')
                    submit_button.wait_for(timeout=5000)
                    submit_button.click()
                    logging.info("Pulsante di invio cliccato.")
                    break
                except Exception as e:
                    logging.debug(f"Submit con selettore {selector} fallito: {e}")
                    continue
            
            if not iframe_page:
                raise Exception("Nessun iframe trovato per il submit")
            
            # Attende la redirezione alla pagina di ringraziamento
            page.wait_for_url('https://toppartners.it/grazie-1/', timeout=15000)
            logging.info("Redirezione alla pagina di ringraziamento riuscita.")
            
            # Aggiornamento immediato del foglio subito dopo il completamento del caricamento della pagina
            update_sheet(sheet, row_idx, True)
            logging.info("Cella aggiornata immediatamente dopo il caricamento della pagina.")

            logging.info("Attesa casuale prima di procedere...")
            time.sleep(random.uniform(WAIT_BEFORE_NEXT_MIN, WAIT_BEFORE_NEXT_MAX))
            logging.info("Attesa casuale completata.")
            
            return True
        except Exception as e:
            logging.error(f"Errore durante il clic sul pulsante di invio o la redirezione alla pagina di ringraziamento: {e}")
            update_sheet(sheet, row_idx, False)
            return False
    except Exception as e:
        logging.error(f"Errore durante il processo di invio per la riga {row_idx}: {e}")
        update_sheet(sheet, row_idx, False)
        return False
    finally:
        # CHIUSURA COMPLETA E PULIZIA TOTALE PER OGNI RIGA
        logging.info(f"Chiusura completa del browser per la riga {row_idx}...")
        if context:
            try:
                context.close()
                logging.debug("Context chiuso con successo.")
            except:
                pass
        if browser:
            try:
                browser.close()
                logging.debug("Browser chiuso con successo.")
            except:
                pass
        if playwright:
            try:
                playwright.stop()
                logging.debug("Playwright fermato con successo.")
            except:
                pass
        
        # Attesa aggiuntiva tra le righe per assicurarsi che tutto sia pulito
        logging.info("Attesa di pulizia tra le righe...")
        time.sleep(2)

def run_buoni_pasto_automation(num_workers=1):
    """
    Esegue l'automazione buoni-pasto integrata
    """
    logging.info("=== Inizio automazione buoni-pasto ===")
    logging.info(f"Numero di worker: {num_workers}")
    
    try:
        # Autenticazione Google Sheets
        logging.info("Autenticazione e connessione a Google Sheets...")
        scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        logging.info(f"Connessione a Google Sheet '{SHEET_NAME}' riuscita.")
        
        column_names = get_column_names(sheet)
        rows_to_upload = find_rows_to_upload(sheet)

        if not rows_to_upload:
            logging.info("Nessun nominativo trovato. Interruzione del processo.")
            return

        logging.info(f"Trovate {len(rows_to_upload)} righe da elaborare.")
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {
                executor.submit(process_entry, row_idx, dict(zip(column_names, sheet.row_values(row_idx))), sheet): row_idx
                for row_idx in rows_to_upload
            }

            for future in as_completed(futures):
                row_idx = futures[future]
                try:
                    result = future.result()
                    if result:
                        logging.info(f"Elaborazione della riga {row_idx} completata con successo.")
                    else:
                        logging.info(f"Elaborazione della riga {row_idx} non andata a buon fine.")
                except Exception as e:
                    logging.error(f"Errore durante l'elaborazione della riga {row_idx}: {e}")
                    update_sheet(sheet, row_idx, False)
        
        logging.info("=== Automazione buoni-pasto completata ===")
        
    except Exception as e:
        logging.error(f"Errore nell'automazione buoni-pasto: {str(e)}")

def main():
    args = parse_arguments()
    global HEADLESS_MODE
    if args.gui:
        HEADLESS_MODE = False
    else:
        HEADLESS_MODE = args.headless
    logging.info("=== Inizio automazione Magellano ===")
    logging.info(f"Modalità headless: {HEADLESS_MODE}")
    campaign_url = "https://magellano.ai/admin/index.php?menuNode=15.04&module=importPanelPublisher&method=main"
    temp_dir = tempfile.mkdtemp()
    try:
        campaigns = get_campaigns_from_args(args)
        start_date, end_date = get_date_range_from_args(args)
        logging.info(f"Campagne da processare: {campaigns}")
        logging.info(f"Range date: {start_date} - {end_date}")
        password = generate_password()
        # Step 2: Download file ZIP per ogni campagna (solo se richiesto)
        if not args.lp:
            with sync_playwright() as playwright:
                for campaign_number in campaigns:
                    logging.info(f"=== Processamento campagna {campaign_number} ===")
                    zip_file = download_campaign_file(playwright, campaign_url, campaign_number, start_date, end_date)
                    if not zip_file:
                        logging.error(f"Errore nel download del file ZIP per la campagna {campaign_number}")
                        continue
                    xls_file = extract_zip_file(zip_file, temp_dir)
                    if not xls_file:
                        logging.error(f"Errore nell'estrazione del file XLS per la campagna {campaign_number}")
                        continue
                    success = process_excel_and_upload_to_sheets(xls_file)
                    if not success:
                        logging.error(f"Errore nel processamento del file Excel per la campagna {campaign_number}")
                        continue
                    logging.info(f"=== Campagna {campaign_number} completata con successo ===")
                    cleanup_files(zip_file, temp_dir)
        logging.info("=== Automazione Magellano completata con successo ===")
        # Step 5: Avvia l'automazione buoni-pasto integrata (solo se richiesto)
        if not args.sheet:
            logging.info("=== Avvio automazione buoni-pasto ===")
            run_buoni_pasto_automation(args.worker)
        else:
            logging.info("=== Automazione buoni-pasto saltata (--sheet) ===")
        logging.info("=== Processo completo terminato ===")
    except Exception as e:
        logging.error(f"Errore generale: {str(e)}")
    finally:
        cleanup_files(None, temp_dir)

if __name__ == "__main__":
    main() 