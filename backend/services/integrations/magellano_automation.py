import os
import logging
import zipfile
import shutil
import pandas as pd
from playwright.sync_api import sync_playwright
from datetime import datetime, date, timedelta
import argparse
import sys
import tempfile

# Inizializza logging se non già configurato (per script standalone)
from logging_config import setup_logging
import logging as std_logging
if not std_logging.getLogger().handlers:
    setup_logging(std_logging.INFO)

# Usa il logger configurato centralmente
logger = logging.getLogger('services.integrations.magellano')

class MagellanoAutomation:
    def __init__(self, username: str = None, password: str = None, headless: bool = True):
        from config import settings
        self.base_url = "https://magellano.ai/admin/index.php"
        self.username = username or settings.MAGELLANO_USER or ""
        self.password = password or settings.MAGELLANO_PASSWORD or ""
        self.headless = headless

    def generate_password(self):
        """Genera la password dinamica: ggmmaaT-Direct"""
        today = date.today()
        return today.strftime("%d%m%Y") + "T-Direct"

    def download_campaign_file(self, playwright, campaign_number, start_date, end_date, download_dir):
        """Scarica il file ZIP da Magellano"""
        logger.info(f"Inizio download campagna {campaign_number} ({start_date} - {end_date})")
        
        browser = playwright.chromium.launch(headless=self.headless)
        context = browser.new_context(
            viewport={'width': 1400, 'height': 900},
            accept_downloads=True,
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = context.new_page()
        
        start_date_str = start_date.strftime('%d%m%Y')
        end_date_str = end_date.strftime('%d%m%Y')
        export_filename = f"export-{campaign_number}-{start_date_str}-{end_date_str}"
        export_filename_xls = f"{export_filename}.xls"
        
        page.on("dialog", lambda dialog: dialog.accept(export_filename) if dialog.type == "prompt" else dialog.accept())

        try:
            # Login + filtro + apertura pannello Users + set date (stato lasciato vuoto) + Export
            self._enqueue_export_common(page, campaign_number, start_date, end_date)

            # Dopo aver richiesto l'export, passa alla lista export e aspetta il completamento
            return self._wait_and_download_export_from_list(page, export_filename_xls, download_dir)
        finally:
            browser.close()

    def enqueue_export_only(self, playwright, campaign_number, start_date, end_date):
        """
        Esegue solo la parte di login/navigazione/click su "Export" per una campagna
        e poi termina SENZA attendere il completamento né scaricare il file.

        Restituisce il nome atteso del file .xls, che può essere usato dallo script 2.
        """
        logger.info(
            "Enqueue export only per campagna %s (%s - %s)",
            campaign_number,
            start_date,
            end_date,
        )

        browser = playwright.chromium.launch(headless=self.headless)
        context = browser.new_context(
            viewport={'width': 1400, 'height': 900},
            accept_downloads=True,
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = context.new_page()

        start_date_str = start_date.strftime('%d%m%Y')
        end_date_str = end_date.strftime('%d%m%Y')
        export_filename = f"export-{campaign_number}-{start_date_str}-{end_date_str}"

        # Imposta il nome dell'export sul prompt
        page.on("dialog", lambda dialog: dialog.accept(export_filename) if dialog.type == "prompt" else dialog.accept())

        try:
            self._enqueue_export_common(page, campaign_number, start_date, end_date)
            # Non andiamo nella lista export, non aspettiamo il completamento, non scarichiamo.
            logger.info("Export richiesto per campagna %s, filename atteso: %s.xls", campaign_number, export_filename)
            return f"{export_filename}.xls"
        finally:
            browser.close()

    def fetch_export_and_process(self, playwright, campaign_number, start_date, end_date, password_date, download_dir):
        """
        Partendo da una richiesta export già effettuata in precedenza (script 1),
        cerca nella lista export un file completato con il nome atteso e, se lo trova,
        lo scarica e lo converte in una lista di dict lead usando la stessa logica
        di parsing di `MagellanoService.process_uploaded_file`.

        Se il file non è pronto/non esiste, restituisce None (sarà il chiamante a
        decidere se considerarlo errore definitivo).
        """
        logger.info(
            "Fetch export and process per campagna %s (%s - %s)",
            campaign_number,
            start_date,
            end_date,
        )
        
        browser = playwright.chromium.launch(headless=self.headless)
        context = browser.new_context(
            viewport={'width': 1400, 'height': 900},
            accept_downloads=True,
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = context.new_page()

        start_date_str = start_date.strftime('%d%m%Y')
        end_date_str = end_date.strftime('%d%m%Y')
        export_filename = f"export-{campaign_number}-{start_date_str}-{end_date_str}.xls"

        try:
            downloaded_path = self._wait_and_download_export_from_list(page, export_filename, download_dir)
            if not downloaded_path:
                logger.warning(
                    "Export non trovato/completato per campagna %s (%s - %s)",
                    campaign_number,
                    start_date,
                    end_date,
                )
                return None

            # Usa la stessa logica di parsing dell'upload manuale per ottenere lead dict,
            # così l'ingestion resta unica. La password ZIP è basata su password_date.
            from services.integrations.magellano import MagellanoService

            service = MagellanoService()
            # Usa end_date come data per la password ZIP (stessa convenzione dell'automatico)
            leads = service.process_uploaded_file(
                downloaded_path,
                password_date,
                campaign_id=campaign_number,
                original_filename=os.path.basename(downloaded_path),
            )
            return leads
        finally:
            browser.close()

    def _enqueue_export_common(self, page, campaign_number, start_date, end_date):
        """
        Parte comune tra:
        - download_campaign_file (vecchia logica)
        - enqueue_export_only (script 1)

        Esegue login, filtro, apertura pannello Users, impostazione date (filtro stato vuoto), click su Export.
        """
        # Login
        page.goto(f"{self.base_url}?menuNode=15.04&module=importPanelPublisher&method=main")
        page.fill("#weblib_username", self.username)
        page.fill("#weblib_password", self.password)
        page.click("a[href*='form_login'].btn-primary")
        page.wait_for_load_state('networkidle')
        
        # Navigate to Campaigns
        page.goto(f"{self.base_url}?menuNode=05.01&module=listCoregs&method=main")
        page.wait_for_load_state('networkidle')
        
        # Filter
        page.click('a[data-rel="collapse"] i.fa-plus')
        page.wait_for_timeout(500)
        page.evaluate(f"""
            $('.select2-choices').click();
            setTimeout(function() {{
                $('.select2-input').val('{campaign_number}').trigger('input').trigger('keyup');
            }}, 500);
        """)
        page.wait_for_timeout(1000)
        page.click(f'.select2-result-label:has-text("{campaign_number}")', timeout=5000)
        page.click('a.btn-success:has-text("Apply filters")')
        page.wait_for_load_state('networkidle')
        
        # Users
        page.click('button[data-original-title="Users"] i.fa-users')
        page.wait_for_load_state('networkidle')
        
        # Inserisci date direttamente nei campi (formato DD/MM/YYYY)
        date_from_str = start_date.strftime('%d/%m/%Y')
        date_to_str = end_date.strftime('%d/%m/%Y')
        logger.info(f"Setting dates: {date_from_str} - {date_to_str}")
        page.locator('#filters_date_from').fill(date_from_str)
        page.locator('#filters_date_to').fill(date_to_str)
        page.evaluate("""
            const fromEl = document.getElementById('filters_date_from');
            const toEl = document.getElementById('filters_date_to');
            if (fromEl) { $(fromEl).trigger('change'); }
            if (toEl) { $(toEl).trigger('change'); }
        """)
        page.wait_for_timeout(500)

        # Stato: non selezionare nulla (vuoto = tutte le lead, come script originale MagellanoService)
        page.evaluate("""
            const select = document.getElementById('filters_sent');
            if (select) {
                select.value = '';
                $(select).trigger('change');
            }
        """)
        page.wait_for_timeout(500)

        page.click('a.btn-success:has-text("Apply filters")')
        page.wait_for_load_state('networkidle')
        
        # Export
        page.click('a.btn-primary:has-text("Export")')
        page.wait_for_timeout(2000)

    def _wait_and_download_export_from_list(self, page, export_filename_xls, download_dir):
        """
        Dalla lista export, cerca un file completato con il nome indicato e, se lo trova,
        lo scarica nella cartella indicata.
        
        Restituisce il percorso del file scaricato oppure None se non trovato/completato
        entro il numero massimo di tentativi.
        """
        # Login rapido se necessario, poi apri la lista export.
        logger.info("Apro lista export Magellano per cercare %s", export_filename_xls)
        page.goto(f"{self.base_url}?menuNode=15.04&module=importPanelPublisher&method=main")
        if page.locator("#weblib_username").count() > 0:
            logger.info("Pagina di login rilevata: eseguo login prima di aprire la lista export")
            page.fill("#weblib_username", self.username)
            page.fill("#weblib_password", self.password)
            page.click("a[href*='form_login'].btn-primary")
            page.wait_for_load_state('networkidle')

        # Export List
        page.goto(f"{self.base_url}?menuNode=10.07&module=listExportsList&method=main")
        
        for attempt in range(20):
            rows = page.locator('table#table-basic tr').all()
            for row in rows:
                if export_filename_xls in row.inner_text() and "completed" in row.inner_text().lower():
                    with page.expect_download() as download_info:
                        row.locator('button[data-original-title="Download"]').click()
                    download = download_info.value
                    save_path = os.path.join(download_dir, download.suggested_filename)
                    download.save_as(save_path)
                    return save_path
            page.wait_for_timeout(3000)
            page.reload()
            
        return None

    def extract_and_work(self, zip_path, extract_dir):
        """Estrae il file ZIP e processa il contenuto"""
        logger.info(f"Estrazione ZIP: {zip_path}")
        password = self.generate_password()
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir, pwd=password.encode('utf-8'))
            
            xls_files = []
            for root, _, files in os.walk(extract_dir):
                for file in files:
                    if file.endswith('.xls') or file.endswith('.xlsx'):
                        xls_files.append(os.path.join(root, file))
            
            if not xls_files:
                return None
            
            xls_path = xls_files[0]
            df = pd.read_excel(xls_path)
            logger.info(f"Processati {len(df)} record dal file {xls_path}")
            return df
        except Exception as e:
            logger.error(f"Errore: {e}", exc_info=True)
            return None

def parse_args():
    parser = argparse.ArgumentParser(description='Magellano Automation Tool')
    parser.add_argument('--campaign', type=int, required=True, help='ID Campagna')
    parser.add_argument('--days', type=int, default=1, help='Giorni da recuperare (default: 1)')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    automation = MagellanoAutomation()
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=args.days)
    
    temp_dir = tempfile.mkdtemp()
    try:
        with sync_playwright() as p:
            zip_path = automation.download_campaign_file(p, args.campaign, start_date, end_date, temp_dir)
            if zip_path:
                df = automation.extract_and_work(zip_path, temp_dir)
                if df is not None:
                    # Qui si può fare il "lavoro" sul dataframe
                    output_file = f"leads_campagna_{args.campaign}.csv"
                    df.to_csv(output_file, index=False)
                    logger.info(f"Dati salvati in {output_file}")
            else:
                logger.error("Download fallito")
    finally:
        shutil.rmtree(temp_dir)