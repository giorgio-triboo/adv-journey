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

# Logging config
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MagellanoService:
    def __init__(self):
        self.base_url = "https://magellano.ai/admin/index.php"
        self.username = settings.MAGELLANO_USER
        self.password = settings.MAGELLANO_PASSWORD

    def generate_password(self) -> str:
        """Generates dynamic ZIP password: ddmmyyyyT-Direct"""
        today = date.today()
        return today.strftime("%d%m%Y") + "T-Direct"

    def fetch_leads(self, start_date: date, end_date: date, campaigns: List[int]) -> List[Dict]:
        """
        Orchestrates the download and parsing of leads from Magellano.
        """
        all_leads = []
        temp_dir = tempfile.mkdtemp()
        
        try:
            with sync_playwright() as p:
                for campaign in campaigns:
                    logger.info(f"Processing campaign {campaign}...")
                    zip_path = self._download_campaign(p, campaign, start_date, end_date, temp_dir)
                    
                    if not zip_path:
                        logger.error(f"Failed to download ZIP for campaign {campaign}")
                        continue

                    xls_path = self._extract_zip(zip_path, temp_dir)
                    if not xls_path:
                        logger.error(f"Failed to extract XLS for campaign {campaign}")
                        continue
                        
                    leads = self._process_excel(xls_path, campaign)
                    all_leads.extend(leads)
                    
        except Exception as e:
            logger.error(f"Error in fetch_leads: {e}")
            raise e
        finally:
            shutil.rmtree(temp_dir)
            
        return all_leads

    def _download_campaign(self, playwright, campaign_id, start_date, end_date, download_dir) -> Optional[str]:
        browser = playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        context = browser.new_context(
            viewport={'width': 1400, 'height': 900},
            accept_downloads=True,
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        )
        page = context.new_page()
        
        # Nome file custom per export
        start_date_str = start_date.strftime('%d%m%Y')
        export_filename = f"export-{campaign_id}-{start_date_str}"
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
            
            # Select Dates
            logger.info(f"Selecting dates: {start_date} - {end_date}")
            self._select_date(page, 0, start_date.day)
            page.wait_for_timeout(500)
            self._select_date(page, 1, end_date.day)
            page.wait_for_timeout(500)
            
            # Select Status "Sent"
            page.evaluate("""
                const select = document.getElementById('filters_sent');
                if (select) {
                    select.value = '1'; 
                    $(select).trigger('change');
                }
            """)
            
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

    def _select_date(self, page, index, day):
        # Open calendar
        page.locator('.input-group-addon .glyphicon-calendar').nth(index).click()
        page.wait_for_timeout(1000)
        # Select day from visible datepicker (avoiding jQuery :visible selector)
        page.evaluate(f"""
            const calendars = Array.from(document.querySelectorAll('.datepicker'));
            const cal = calendars.find(c => getComputedStyle(c).display !== 'none');
            if (cal) {{
                const days = cal.querySelectorAll('td.day');
                for (let d of days) {{
                    if (d.textContent.trim() === '{day}' && !d.classList.contains('old') && !d.classList.contains('new')) {{
                        d.click();
                        break;
                    }}
                }}
            }}
        """)

    def _extract_zip(self, zip_path, extract_to) -> Optional[str]:
        try:
            password = self.generate_password()
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(extract_to, pwd=password.encode('utf-8'))
                
            for root, _, files in os.walk(extract_to):
                for f in files:
                    if f.endswith('.xls') or f.endswith('.xlsx'):
                        return os.path.join(root, f)
            return None
        except Exception as e:
            logger.error(f"ZIP extraction failed: {e}")
            return None

    def _process_excel(self, xls_path, campaign_id) -> List[Dict]:
        try:
            df = pd.read_excel(xls_path)
            leads = []
            
            for _, row in df.iterrows():
                # Map based on identified columns from inspection
                email = str(row.get('Email', '')).strip()
                if not email or pd.isna(row.get('Email')):
                    continue
                
                # External User ID is a good candidate for dedup
                ext_user_id = str(row.get('Id user', ''))
                
                # Estrai payout status (sent = pagata, blocked/altri = scartata)
                payout_status_raw = str(row.get('Status', '')).strip() if not pd.isna(row.get('Status', '')) else None
                payout_status = None
                is_paid = False
                
                if payout_status_raw:
                    payout_status = payout_status_raw.lower()
                    # "sent" significa pagata, tutto il resto è scartata
                    is_paid = (payout_status == 'sent')
                
                leads.append({
                    'magellano_id': f"MAG-{ext_user_id}",
                    'external_user_id': ext_user_id,
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
                    # Payout status da Magellano
                    'payout_status': payout_status,
                    'is_paid': is_paid,
                    # Facebook/Meta fields from Magellano
                    'facebook_ad_name': str(row.get('facebook_ad_name', '')).strip() if not pd.isna(row.get('facebook_ad_name', '')) else None,
                    'facebook_ad_set': str(row.get('facebook_ad_set', '')).strip() if not pd.isna(row.get('facebook_ad_set', '')) else None,
                    'facebook_campaign_name': str(row.get('facebook_campaign_name', '')).strip() if not pd.isna(row.get('facebook_campaign_name', '')) else None,
                    'facebook_id': str(row.get('facebook_id', '')).strip() if not pd.isna(row.get('facebook_id', '')) else None,  # ID utente Facebook
                    'facebook_piattaforma': str(row.get('facebook_piattaforma', '')).strip() if not pd.isna(row.get('facebook_piattaforma', '')) else None,
                    'status_category': 'in_lavorazione'
                })
            
            return leads

        except Exception as e:
            logger.error(f"Excel processing failed: {e}")
            return []
