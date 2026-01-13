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

# Configurazione del logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)

class MagellanoAutomation:
    def __init__(self, username="giorgio", password="Magellano2025!"):
        self.base_url = "https://magellano.ai/admin/index.php"
        self.username = username
        self.password = password

    def generate_password(self):
        """Genera la password dinamica: ggmmaaT-Direct"""
        today = date.today()
        return today.strftime("%d%m%Y") + "T-Direct"

    def download_campaign_file(self, playwright, campaign_number, start_date, end_date, download_dir):
        """Scarica il file ZIP da Magellano"""
        logging.info(f"Inizio download campagna {campaign_number} ({start_date} - {end_date})")
        
        browser = playwright.chromium.launch(headless=True)
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
            
            # Dates
            self._select_date(page, 0, start_date.day)
            self._select_date(page, 1, end_date.day)
            
            # Sent Status
            page.evaluate("$('#filters_sent').val('1').trigger('change');")
            page.click('a.btn-success:has-text("Apply filters")')
            page.wait_for_load_state('networkidle')
            
            # Export
            page.click('a.btn-primary:has-text("Export")')
            page.wait_for_timeout(2000)
            
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
        finally:
            browser.close()

    def _select_date(self, page, index, day):
        page.locator('.input-group-addon .glyphicon-calendar').nth(index).click()
        page.wait_for_timeout(500)
        page.evaluate(f"""
            const cals = document.querySelectorAll('.datepicker:visible');
            const cal = cals[0];
            if (cal) {{
                const days = cal.querySelectorAll('td.day');
                for (let d of days) {{
                    if (d.textContent.strip() === '{day}' && !d.classList.contains('old') && !d.classList.contains('new')) {{
                        d.click();
                        break;
                    }}
                }}
            }}
        """)

    def extract_and_work(self, zip_path, extract_dir):
        """Estrae il file ZIP e processa il contenuto"""
        logging.info(f"Estrazione ZIP: {zip_path}")
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
            logging.info(f"Processati {len(df)} record dal file {xls_path}")
            return df
        except Exception as e:
            logging.error(f"Errore: {e}")
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
                    logging.info(f"Dati salvati in {output_file}")
            else:
                logging.error("Download fallito")
    finally:
        shutil.rmtree(temp_dir)