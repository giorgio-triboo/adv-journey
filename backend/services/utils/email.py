"""
Servizio per invio email di alert e notifiche.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Dict
from datetime import datetime
import logging
from config import settings

logger = logging.getLogger(__name__)

class EmailService:
    """Servizio per invio email"""
    
    def __init__(self, db: Optional[object] = None):
        """
        Inizializza EmailService.
        
        Args:
            db: Session database opzionale. Se fornito, carica configurazione SMTP dal database.
                Altrimenti usa configurazione da settings (.env)
        """
        # Prova a caricare configurazione dal database se disponibile
        if db:
            try:
                from models import SMTPConfig
                from services.utils.crypto import decrypt_token
                
                smtp_config = db.query(SMTPConfig).filter(SMTPConfig.is_active == True).first()
                if smtp_config:
                    # Usa configurazione dal database
                    self.smtp_host = decrypt_token(smtp_config.host) if smtp_config.host else None
                    self.smtp_port = smtp_config.port or 587
                    self.smtp_user = decrypt_token(smtp_config.user) if smtp_config.user else None
                    self.smtp_password = decrypt_token(smtp_config.password) if smtp_config.password else None
                    self.smtp_from = decrypt_token(smtp_config.from_email) if smtp_config.from_email else self.smtp_user
                    self.use_tls = smtp_config.use_tls if smtp_config.use_tls is not None else True
                    logger.info("EmailService: usando configurazione SMTP dal database")
                    return
            except Exception as e:
                logger.warning(f"Errore caricamento SMTP config dal database: {e}. Uso configurazione da settings.")
        
        # Fallback a configurazione da settings
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT or 587
        self.smtp_user = settings.SMTP_USER
        self.smtp_password = settings.SMTP_PASSWORD
        self.smtp_from = settings.SMTP_FROM_EMAIL or settings.SMTP_USER
        self.use_tls = settings.SMTP_USE_TLS
    
    def is_configured(self) -> bool:
        """Verifica se SMTP è configurato"""
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)
    
    def send_alert(
        self,
        recipients: List[str],
        subject: str,
        body_html: str,
        body_text: Optional[str] = None
    ) -> bool:
        """
        Invia email di alert.
        
        Args:
            recipients: Lista di indirizzi email destinatari
            subject: Oggetto email
            body_html: Corpo email in HTML
            body_text: Corpo email in testo (opzionale, generato da HTML se non fornito)
        
        Returns:
            True se inviata con successo, False altrimenti
        """
        if not self.is_configured():
            logger.warning("SMTP non configurato. Email non inviata.")
            return False
        
        if not recipients:
            logger.warning("Nessun destinatario specificato. Email non inviata.")
            return False
        
        try:
            # Crea messaggio
            msg = MIMEMultipart('alternative')
            msg['From'] = self.smtp_from
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = subject
            
            # Aggiungi corpo testo (se non fornito, genera da HTML)
            if body_text:
                msg.attach(MIMEText(body_text, 'plain'))
            else:
                # Genera testo semplice da HTML (rimuove tag)
                import re
                text_body = re.sub(r'<[^>]+>', '', body_html)
                text_body = text_body.replace('&nbsp;', ' ')
                msg.attach(MIMEText(text_body, 'plain'))
            
            # Aggiungi corpo HTML
            msg.attach(MIMEText(body_html, 'html'))
            
            # Invia email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                
                server.send_message(msg)
            
            logger.info(f"Email inviata con successo a {len(recipients)} destinatari: {subject}")
            return True
            
        except Exception as e:
            logger.error(f"Errore invio email: {e}", exc_info=True)
            return False
    
    def send_sync_alert(
        self,
        sync_type: str,
        success: bool,
        stats: Dict,
        recipients: List[str],
        error_message: Optional[str] = None
    ) -> bool:
        """
        Invia alert per sync job.
        
        Args:
            sync_type: Tipo sync ('magellano', 'ulixe', 'meta_marketing', 'meta_conversion')
            success: True se successo, False se errore
            stats: Dizionario con statistiche sync
            recipients: Lista destinatari
            error_message: Messaggio errore (se success=False)
        
        Returns:
            True se inviata con successo
        """
        sync_names = {
            'magellano': 'Magellano',
            'ulixe': 'Ulixe',
            'meta_marketing': 'Meta Marketing',
            'meta_conversion': 'Meta Conversion API'
        }
        
        sync_name = sync_names.get(sync_type, sync_type)
        status_emoji = "✅" if success else "❌"
        status_text = "Completato con successo" if success else "Errore"
        
        subject = f"{status_emoji} Sync {sync_name} - {status_text}"
        
        # Genera HTML (passa status_text per usarlo nel template)
        html_body = self._generate_sync_alert_html(
            sync_name, success, stats, error_message, status_text
        )
        
        return self.send_alert(recipients, subject, html_body)
    
    def _generate_sync_alert_html(
        self,
        sync_name: str,
        success: bool,
        stats: Dict,
        error_message: Optional[str] = None,
        status_text: Optional[str] = None
    ) -> str:
        """Genera HTML per alert sync"""
        if status_text is None:
            status_text = "Completato con successo" if success else "Errore"
        timestamp = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        
        if success:
            status_color = "#10b981"  # green
            status_bg = "#d1fae5"
        else:
            status_color = "#ef4444"  # red
            status_bg = "#fee2e2"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: {status_bg}; color: {status_color}; padding: 20px; border-radius: 8px 8px 0 0; }}
                .content {{ background: #ffffff; padding: 20px; border: 1px solid #e5e7eb; }}
                .stats {{ background: #f9fafb; padding: 15px; border-radius: 4px; margin: 15px 0; }}
                .stat-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #e5e7eb; }}
                .stat-row:last-child {{ border-bottom: none; }}
                .stat-label {{ font-weight: 600; color: #6b7280; }}
                .stat-value {{ font-weight: 700; color: #111827; }}
                .error-box {{ background: #fee2e2; border-left: 4px solid #ef4444; padding: 15px; margin: 15px 0; }}
                .footer {{ background: #f9fafb; padding: 15px; text-align: center; color: #6b7280; font-size: 12px; border-radius: 0 0 8px 8px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2 style="margin: 0;">Sync {sync_name}</h2>
                    <p style="margin: 5px 0 0 0;">{status_text}</p>
                </div>
                <div class="content">
                    <p><strong>Timestamp:</strong> {timestamp}</p>
                    
                    <div class="stats">
                        <h3 style="margin-top: 0;">Statistiche</h3>
        """
        
        # Aggiungi statistiche
        for key, value in stats.items():
            if isinstance(value, (int, float)):
                html += f"""
                        <div class="stat-row">
                            <span class="stat-label">{key.replace('_', ' ').title()}:</span>
                            <span class="stat-value">{value}</span>
                        </div>
                """
            elif isinstance(value, dict):
                for sub_key, sub_val in value.items():
                    html += f"""
                        <div class="stat-row">
                            <span class="stat-label">{key} - {sub_key.replace('_', ' ').title()}:</span>
                            <span class="stat-value">{sub_val}</span>
                        </div>
                """
            elif value is not None and value != "":
                html += f"""
                        <div class="stat-row">
                            <span class="stat-label">{key.replace('_', ' ').title()}:</span>
                            <span class="stat-value">{value}</span>
                        </div>
                """
        
        html += """
                    </div>
        """
        
        # Aggiungi messaggio errore se presente
        if error_message:
            html += f"""
                    <div class="error-box">
                        <strong>Errore:</strong><br>
                        {error_message}
                    </div>
            """
        
        # Link al riepilogo ingestion (solo su errore)
        ingestion_link = ""
        if not success and settings.APP_BASE_URL:
            ingestion_url = settings.APP_BASE_URL.rstrip("/") + "/settings/alerts/ingestion"
            ingestion_link = f"""
                    <p style="margin-top: 15px;">
                        <a href="{ingestion_url}" style="display: inline-block; padding: 10px 20px; background: #4f46e5; color: white; text-decoration: none; border-radius: 6px; font-weight: 600;">
                            Vai al Riepilogo Ingestion
                        </a>
                    </p>
            """
        
        html += f"""
                </div>
                <div class="footer">
                    {ingestion_link}
                    <p>Questo è un messaggio automatico dal sistema Cepu Lavorazioni.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return html
