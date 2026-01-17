"""
Configurazione logging per l'applicazione.
Scrive i log sia su console che su file locale per debug.
Divide i log per giorno e per sezione/modulo.
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from datetime import datetime


def _get_log_filename_with_date(log_dir: Path, prefix: str) -> Path:
    """
    Genera il nome del file di log con la data corrente.
    Formato: {prefix}-YYYY-MM-DD.log
    
    Args:
        log_dir: Directory dei log
        prefix: Prefisso del file (es: 'app', 'api-ui', etc.)
    
    Returns:
        Path completo del file di log con data
    """
    today = datetime.now().strftime('%Y-%m-%d')
    return log_dir / f"{prefix}-{today}.log"


class DailyRotatingFileHandler(TimedRotatingFileHandler):
    """
    Handler per file di log con rotazione giornaliera e data nel nome del file.
    Crea file con formato: {prefix}-YYYY-MM-DD.log
    """
    def __init__(self, log_dir: Path, prefix: str, backupCount=7, encoding='utf-8'):
        """
        Args:
            log_dir: Directory dove salvare i log
            prefix: Prefisso del file (es: 'app', 'api-ui', etc.)
            backupCount: Numero di giorni di backup da mantenere
            encoding: Encoding del file (default: utf-8)
        """
        self.log_dir = Path(log_dir)
        self.prefix = prefix
        self.log_dir.mkdir(exist_ok=True)
        
        # Genera il nome del file con la data corrente
        log_file = _get_log_filename_with_date(self.log_dir, prefix)
        
        # Inizializza TimedRotatingFileHandler con rotazione giornaliera
        super().__init__(
            filename=str(log_file),
            when='midnight',
            interval=1,
            backupCount=backupCount,
            encoding=encoding
        )
    
    def doRollover(self):
        """
        Override del metodo doRollover per usare il nome del file con data.
        """
        # Chiudi il file corrente
        if self.stream:
            self.stream.close()
            self.stream = None
        
        # Genera il nuovo nome del file con la data corrente
        log_file = _get_log_filename_with_date(self.log_dir, self.prefix)
        
        # Aggiorna il nome del file base
        self.baseFilename = str(log_file)
        
        # Apri il nuovo file
        if not self.delay:
            self.stream = self._open()


def _cleanup_empty_log_files(log_dir, log_messages=False):
    """
    Elimina i file di log vuoti dalla directory dei log.
    I file vuoti vengono creati da TimedRotatingFileHandler anche se non ci sono log da scrivere.
    
    Args:
        log_dir: Directory contenente i file di log
        log_messages: Se True, logga i messaggi (solo se il logging è già configurato)
    """
    try:
        for log_file in log_dir.glob("*.log"):
            # Controlla se il file esiste ed è vuoto (0 byte o contiene solo whitespace)
            if log_file.exists():
                try:
                    # Leggi il contenuto del file
                    content = log_file.read_text(encoding='utf-8').strip()
                    # Se il file è vuoto o contiene solo whitespace, eliminalo
                    if not content:
                        log_file.unlink()
                        if log_messages:
                            logging.debug(f"Eliminato file di log vuoto: {log_file.name}")
                except Exception as e:
                    # Se c'è un errore nella lettura, lascia il file
                    if log_messages:
                        logging.warning(f"Impossibile verificare il file {log_file.name}: {e}")
    except Exception as e:
        if log_messages:
            logging.warning(f"Errore durante la pulizia dei file di log vuoti: {e}")

def setup_logging(log_level=logging.INFO):
    """
    Configura il logging per l'applicazione.
    Scrive i log su console e su file locale.
    Divide i log per giorno e per sezione/modulo.
    
    Args:
        log_level: Livello di logging (default: INFO)
    """
    # Determina il percorso base (funziona sia in locale che in Docker)
    base_dir = Path(__file__).parent
    log_dir = base_dir / "logs"
    log_dir.mkdir(exist_ok=True)
    
    # Elimina i file di log vuoti esistenti prima di configurare il logging
    _cleanup_empty_log_files(log_dir)
    
    # Formato dei log con data, ora e millisecondi per debug preciso
    log_format = '%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # Configura root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Rimuovi handler esistenti per evitare duplicati
    root_logger.handlers = []
    
    # Handler per console (stderr)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_formatter = logging.Formatter(log_format, date_format)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # Handler per file generale con rotazione giornaliera e data nel nome
    general_handler = DailyRotatingFileHandler(
        log_dir,
        "app",
        backupCount=7,  # Mantiene 7 giorni di log
        encoding='utf-8'
    )
    general_handler.setLevel(log_level)
    general_formatter = logging.Formatter(log_format, date_format)
    general_handler.setFormatter(general_formatter)
    root_logger.addHandler(general_handler)
    
    # Ottieni il nome del file corrente per il messaggio di log
    general_log_file = Path(general_handler.baseFilename)
    
    # Definizione delle sezioni con i loro logger e file
    sections = {
        'api-ui': {
            'logger_name': 'services.api.ui',
            'file_prefix': 'api-ui',
            'level': logging.DEBUG
        },
        'api-auth': {
            'logger_name': 'services.api.auth',
            'file_prefix': 'api-auth',
            'level': logging.DEBUG
        },
        'api-leads': {
            'logger_name': 'services.api.leads',
            'file_prefix': 'api-leads',
            'level': logging.DEBUG
        },
        'integrations-meta': {
            'logger_name': 'services.integrations.meta_marketing',
            'file_prefix': 'integrations-meta',
            'level': logging.DEBUG
        },
        'integrations-magellano': {
            'logger_name': 'services.integrations.magellano',
            'file_prefix': 'integrations-magellano',
            'level': logging.DEBUG
        },
        'integrations-ulixe': {
            'logger_name': 'services.integrations.ulixe',
            'file_prefix': 'integrations-ulixe',
            'level': logging.DEBUG
        },
        'sync': {
            'logger_name': 'services.sync',
            'file_prefix': 'sync',
            'level': logging.DEBUG
        },
        'sync-orchestrator': {
            'logger_name': 'services.sync_orchestrator',
            'file_prefix': 'sync-orchestrator',
            'level': logging.DEBUG
        },
        'scheduler': {
            'logger_name': 'services.scheduler',
            'file_prefix': 'scheduler',
            'level': logging.DEBUG
        },
        'database': {
            'logger_name': 'database',
            'file_prefix': 'database',
            'level': logging.DEBUG
        }
    }
    
    # Crea handler separati per ogni sezione
    for section_name, section_config in sections.items():
        section_logger = logging.getLogger(section_config['logger_name'])
        section_logger.setLevel(section_config['level'])
        section_logger.propagate = False  # Non propagare al root logger per evitare duplicati
        
        # File di log per questa sezione con rotazione giornaliera e data nel nome
        section_handler = DailyRotatingFileHandler(
            log_dir,
            section_config['file_prefix'],
            backupCount=7,  # Mantiene 7 giorni di log
            encoding='utf-8'
        )
        section_handler.setLevel(section_config['level'])
        section_formatter = logging.Formatter(log_format, date_format)
        section_handler.setFormatter(section_formatter)
        section_logger.addHandler(section_handler)
        
        # Aggiungi anche console handler per questa sezione
        section_console_handler = logging.StreamHandler()
        section_console_handler.setLevel(section_config['level'])
        section_console_handler.setFormatter(console_formatter)
        section_logger.addHandler(section_console_handler)
    
    logging.info(f"Logging configurato. Directory log: {log_dir.absolute()}")
    logging.info(f"File di log generale: {general_log_file.absolute()}")
    logging.info(f"File di log per sezione disponibili in: {log_dir.absolute()}")
    
    # Flush di tutti gli handler per assicurarsi che i log vengano scritti
    for handler in root_logger.handlers:
        if hasattr(handler, 'flush'):
            handler.flush()
    
    for section_name, section_config in sections.items():
        section_logger = logging.getLogger(section_config['logger_name'])
        for handler in section_logger.handlers:
            if hasattr(handler, 'flush'):
                handler.flush()
    
    # NON eliminare i file vuoti subito dopo la configurazione
    # I file verranno creati quando ci saranno log da scrivere
    # _cleanup_empty_log_files(log_dir, log_messages=True)
    
    return general_log_file
