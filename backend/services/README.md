# Services Directory Structure

## 📁 Organizzazione

```
services/
├── api/                    # FastAPI routers e endpoints
│   ├── auth.py            # Autenticazione Google OAuth
│   ├── leads.py           # API REST per leads
│   └── ui.py              # Endpoints UI (dashboard, settings)
│
├── integrations/          # Servizi per integrazioni esterne
│   ├── magellano.py       # Service Magellano (fetch leads)
│   ├── magellano_automation.py  # Automazione Playwright per Magellano
│   ├── ulixe.py           # Client SOAP Ulixe
│   ├── meta.py            # Meta Conversion API
│   └── meta_marketing.py  # Meta Marketing API (Graph API)
│
├── sync/                  # Job di sincronizzazione autonomi
│   ├── magellano_sync.py  # Job: Recupera e salva dati Magellano
│   ├── ulixe_sync.py      # Job: Sync stati Ulixe (esclude NO CRM)
│   ├── meta_marketing_sync.py  # Job: Ingestion dati marketing Meta
│   └── meta_conversion_sync.py # Job: Invia eventi Conversion API
│
├── sync_orchestrator.py   # Orchestrator per eseguire job in sequenza
└── scheduler.py           # Scheduler APScheduler (00:30)
```

## 🔄 Flusso Sincronizzazione

### Orchestrator Pattern
L'`SyncOrchestrator` gestisce l'esecuzione sequenziale di tutti i job:

1. **magellano_sync** → Recupera lead da Magellano e salva in DB
2. **ulixe_sync** → Controlla stati Ulixe per lead senza "NO CRM"
3. **meta_marketing_sync** → Ingestion dati marketing da Meta
4. **meta_conversion_sync** → Invia eventi Conversion API

### Aggiungere Nuove Piattaforme

Per aggiungere una nuova piattaforma:

1. Creare nuovo file in `sync/` (es. `nuova_piattaforma_sync.py`)
2. Implementare funzione `run(db: Session = None) -> dict`
3. Aggiungere all'orchestrator:
   ```python
   orchestrator.add_job(
       name="nuova_piattaforma",
       job_func=nuova_piattaforma_sync.run,
       description="Descrizione job"
   )
   ```

## 📝 Note

- Ogni job in `sync/` è completamente autonomo e può essere eseguito singolarmente
- Gli import usano percorsi relativi al package (es. `services.integrations.magellano`)
- L'orchestrator gestisce la sessione DB condivisa per tutti i job
