# 🗺️ Roadmap di Implementazione

Questo documento contiene la lista dettagliata di tutte le task da implementare, organizzate per area funzionale, senza priorità o schedulazioni.

---

## 📊 Visualizzazione e Analytics

### Grafici Performance nella Dashboard Analytics
**Obiettivo**: Aggiungere grafici interattivi per visualizzare trend e distribuzione dati

**Task**:
- Scegliere libreria grafici (Chart.js, Plotly, o ApexCharts)
- Implementare grafici trend (spend, conversioni nel tempo)
- Implementare grafici distribuzione (per campagna, adset, ad)
- Implementare heatmap performance
- Implementare confronto periodi
- Integrare grafici nella pagina `/analytics`
- Aggiungere filtri per personalizzare visualizzazione

**Endpoint**: `/analytics` (già esistente)

**File da modificare**:
- `frontend/templates/analytics.html`
- `backend/services/api/ui.py` (se necessario endpoint aggiuntivi)

---

## 📤 Export e Report

### Export CSV/Excel
**Obiettivo**: Permettere export dati combinati in formato CSV/Excel

**Task**:
- Creare endpoint `/api/export/csv` con filtri
- Creare endpoint `/api/export/excel` con filtri
- Implementare export dati lead (anagrafica, stato)
- Implementare export dati marketing (campagna, adset, ad, metriche)
- Implementare export storico lavorazioni Ulixe
- Creare template frontend per download
- Gestione file grandi (streaming se necessario)

**Librerie**: `pandas` per manipolazione dati, `openpyxl` per Excel

**File da creare/modificare**:
- `backend/services/api/ui.py` (endpoint export)
- `frontend/templates/` (template export)

### Report Periodici Configurabili
**Obiettivo**: Sistema di report automatici configurabili

**Task**:
- Creare modello DB per configurazione report
- Implementare report giornaliero
- Implementare report settimanale
- Implementare report mensile
- Creare template report personalizzabili
- Implementare invio automatico via email
- Interfaccia per configurazione report

**Endpoint da creare**: `/api/reports` (CRUD report)

**File da creare/modificare**:
- `backend/models.py` (modello ReportConfig)
- `backend/services/api/ui.py` (endpoint report)
- `frontend/templates/` (template configurazione)

### Alert Configurabili
**Obiettivo**: Sistema di alert configurabili per soglie e anomalie

**Task**:
- Creare modello DB per configurazione alert
- Implementare alert CPL sopra soglia
- Implementare alert conversioni sotto soglia
- Implementare alert anomalie performance
- Implementare notifiche errori critici
- Interfaccia per configurazione alert

**Endpoint da creare**: `/api/alerts` (configurazione alert)

**Nota**: Alert email già implementato (F), estendere con alert configurabili

---

## 🔄 Sync e Ingestion

### Logica Selezione Lead per Ulixe - Miglioramenti
**Obiettivo**: Migliorare criteri di selezione lead per sync Ulixe

**Task**:
- Implementare criterio data ultimo check (non controllare troppo spesso)
- Implementare criterio stato attuale (priorità per alcuni stati)
- Implementare criterio età lead (lead troppo vecchie?)
- Implementare finestra temporale configurabile
- Limite max 1 mese per batch (per query molto grosse)
- Query singole: nessun limite temporale

**File da modificare**: `backend/services/sync/ulixe_sync.py`

### Update Magellano con Stati Ulixe
**Obiettivo**: Aggiornare Magellano con stati lavorazione Ulixe

**Task**:
- Creare metodo `update_lead_status()` in `MagellanoService`
- Implementare mapping stati Ulixe → valori Magellano
- Integrare nel flusso scheduler (quando necessario)
- Testare aggiornamento via API Magellano

**Nota**: Da implementare solo se serve effettivamente aggiornare Magellano

**File da modificare**: `backend/services/integrations/magellano.py`

### Sync Automatica Magellano per Singola Campagna
**Obiettivo**: Possibilità di lanciare sync automatica da frontend per singola campagna

**Task**:
- Creare pagina `/settings/magellano/sync` o sezione in upload
- Creare form con dropdown/input per ID campagna
- Aggiungere date range (start_date, end_date)
- Creare endpoint `/api/magellano/sync/campaign` (POST)
- Implementare background task per singola campagna
- Validazione ID campagna esistente
- Feedback progress sync
- Possibilità di sync multiple campagne (checkbox multi-select)
- Log sync manuali vs automatiche

**File da modificare**: 
- `backend/services/api/ui.py` (endpoint sync)
- `frontend/templates/` (template sync)

### Maschera Ingestion Meta per Singolo Account
**Obiettivo**: Creare maschera dedicata per forzare sync Meta per singolo account

**Task**:
- Creare pagina `/settings/meta-accounts/{account_id}/sync` o pulsante in dettaglio
- Creare form/pulsante "Sync Now" per account specifico
- Creare endpoint `/api/meta-accounts/{account_id}/sync` (POST)
- Implementare background task per account specifico
- Prevenire sync multiple simultanee per stesso account
- Mostrare ultima sync e prossima sync programmata
- Log sync manuali
- Possibilità di schedulare sync ricorrente per account
- Feedback UI (loading, progress, risultato)

**File da modificare**:
- `backend/services/api/ui.py` (endpoint sync account)
- `frontend/templates/settings_meta_accounts.html` (pulsante sync)

### Maschera Ingestion Ulixe
**Obiettivo**: Creare maschera per forzare sync Ulixe manualmente

**Task**:
- Creare pagina `/settings/ulixe/sync` o sezione in settings
- Creare pulsante "Sync Now" per forzare sync Ulixe
- Opzioni avanzate (opzionali):
  - Filtro per lead specifiche (ID, campagna, stato)
  - Limite numero lead da controllare
- Creare endpoint `/api/ulixe/sync` (POST)
- Implementare background task
- Feedback UI (statistiche, tempo esecuzione, lista errori)
- Mostrare progress approssimativo
- Possibilità di interrompere sync (se necessario)
- Log sync manuali vs automatiche

**File da modificare**:
- `backend/services/api/ui.py` (endpoint sync Ulixe)
- `frontend/templates/` (template sync Ulixe)

---

## ⚙️ Settings e Configurazione

### Settings Avanzati Configurabili
**Obiettivo**: Spostare configurazioni hardcoded in DB con interfaccia

**Task**:
- Creare sezione `/settings/advanced`
- Implementare configurazione scheduler (orari, frequenze)
- Implementare configurazione rate limiting
- Implementare configurazione retention dati
- Implementare configurazione notifiche/alert
- Rimuovere hardcoding da backend
- Spostare configurazioni in DB
- Creare interfaccia per operatori non tecnici
- Implementare validazione configurazioni

**Modelli DB da creare**: `Configuration`, `SchedulerConfig`, `RateLimitConfig`

**File da modificare**:
- `backend/models.py` (modelli configurazione)
- `backend/services/api/ui.py` (endpoint settings)
- `frontend/templates/` (template settings avanzati)

### Miglioramenti UI Ingestion Campagne Meta

#### Vista Globale con Filtro Tag
**Obiettivo**: Semplificare vista campagne, mostrare solo numero totale con filtro tag

**Task**:
- Modificare `/settings/meta-campaigns`:
  - Rimuovere lista dettagliata campagne (o renderla opzionale)
  - Mostrare card con metriche aggregate:
    - Totale campagne
    - Totale adset
    - Totale creatività
    - Spesa totale
    - Lead totali
- Implementare filtro tag:
  - Dropdown/multi-select per filtrare per tag
  - Tag da `MetaCampaign.tags` (se presente) o da `MetaCampaign.campaign_name` (parsing)
  - Aggiornamento metriche in real-time al cambio filtro

**Endpoint da modificare**: `/api/meta-campaigns/stats` (con filtro tag)

**Considerazioni**:
- Se tag non esistono nel DB, creare sistema di tagging
- Considerare auto-tagging basato su pattern nel nome campagna
- Export dati filtrati per tag

#### Pulsante Sync Forzato
**Obiettivo**: Aggiungere pulsante per forzare nuova sync manuale

**Task**:
- Aggiungere pulsante "Sync Now" nella pagina `/settings/meta-campaigns`
- Creare endpoint `/api/meta-campaigns/sync` (POST)
- Implementare background task che esegue `meta_marketing_sync_job`
- Prevenire sync multiple simultanee (lock)
- Mostrare progress se possibile
- Log sync manuali vs automatiche
- Feedback UI (loading state, notifica successo/errore, timestamp ultima sync)

**File da modificare**: `frontend/templates/settings_meta_campaigns.html`

#### Allineamento Pulsante Filtro
**Obiettivo**: Fix problemi di allineamento UI pulsante filtro

**Task**:
- Review CSS/Tailwind per allineamento
- Test responsive su diversi dispositivi
- Fix layout form filtri

**File da modificare**: `frontend/templates/settings_meta_campaigns.html`

#### Pagina Dettaglio Account
**Obiettivo**: Creare pagina per vedere dettagli account con lista campagne

**Task**:
- Creare nuova pagina `/settings/meta-accounts/{account_id}`
- Mostrare dettagli account:
  - Nome account
  - Account ID
  - Token status (valido/scaduto)
  - Ultima sync
  - Statistiche aggregate
- Mostrare lista campagne dell'account:
  - Tabella con tutte le campagne
  - Filtri e ricerca
  - Link a dettaglio campagna (se necessario)
- Implementare paginazione per account con molte campagne
- Export campagne per account
- Possibilità di disabilitare sync per singolo account

**Endpoint da creare**: `/api/meta-accounts/{account_id}` (GET)

**File da creare/modificare**:
- `backend/services/api/ui.py` (endpoint dettaglio account)
- `frontend/templates/settings_meta_accounts_detail.html`

---

## 🏗️ Infrastruttura e Performance

### Virtual Environment Setup
**Obiettivo**: Impostare tutto applicativo dentro venv

**Task**:
- Verificare struttura progetto:
  - `requirements.txt` già presente
  - Creare `venv/` o usare Docker (già presente)
- Se Docker:
  - Verificare che Dockerfile usi venv o installazione diretta
  - Documentare setup venv locale per sviluppo
- Se non Docker:
  - Creare script `setup.sh` per creare venv e installare dipendenze
  - Creare `.env.example` per variabili ambiente
  - Documentazione setup

**File da creare/modificare**:
- `setup.sh` (se necessario)
- `.env.example` (se necessario)
- `README.md` (documentazione)

### Script Esterno di Monitoraggio Healthcheck
**Obiettivo**: Sistema esterno che fa ping e restart in caso di crash

**Task**:
- Creare script bash/Python che fa ping ogni X secondi
- Se non risponde: restart applicazione
- Log tentativi restart
- Opzioni implementazione:
  1. Docker healthcheck (se in Docker) - già implementato
  2. Systemd service (se su server Linux)
  3. Supervisor (process manager)
  4. Script esterno cron

**Script healthcheck esempio**:
```bash
#!/bin/bash
HEALTH_URL="http://localhost:8000/health"
MAX_FAILURES=3
FAILURES=0

while true; do
    if curl -f "$HEALTH_URL" > /dev/null 2>&1; then
        FAILURES=0
    else
        FAILURES=$((FAILURES + 1))
        if [ $FAILURES -ge $MAX_FAILURES ]; then
            echo "Healthcheck failed $MAX_FAILURES times. Restarting..."
            docker-compose restart backend  # o systemctl restart app
            FAILURES=0
        fi
    fi
    sleep 30
done
```

**Considerazioni**:
- Healthcheck non deve essere troppo pesante
- Evitare restart loop infiniti (circuit breaker)
- Notifiche quando restart avviene
- Log dettagliati per debugging

### Ottimizzazioni Performance
**Obiettivo**: Migliorare performance per grandi volumi

**Task**:
- Implementare batch processing per grandi volumi
- Implementare caching dati Meta (evitare chiamate duplicate)
- Implementare retry logic con exponential backoff
- Implementare circuit breaker per servizi esterni
- Aggiungere indicizzazione DB per query veloci
- Implementare background jobs per operazioni pesanti

**Librerie suggerite**: 
- Redis per caching
- Celery per background jobs
- Tenacity per retry logic

**File da modificare**:
- `backend/services/integrations/` (caching, retry)
- `backend/database.py` (indicizzazione)
- `backend/services/scheduler.py` (background jobs)

---

## 🏢 Multi-tenant e Scalabilità

### Multi-tenant Configurabile
**Obiettivo**: Gestione brand/corsi multipli con isolamento dati

**Task**:
- Implementare gestione brand/corsi multipli
- Implementare isolamento dati per tenant
- Implementare configurazione per tenant
- Implementare sistema di ruoli per tenant
- Aggiungere `tenant_id` a tutte le tabelle principali

**Nota**: Da implementare quando necessario

**Modelli DB da modificare**: Aggiungere `tenant_id` a tutte le tabelle principali

**File da modificare**:
- `backend/models.py` (aggiungere tenant_id)
- `backend/services/api/` (filtri per tenant)
- Migration Alembic per aggiungere colonne

---

## 📋 Funzionalità Aggiuntive

### Dashboard Widget Personalizzabili
**Obiettivo**: Widget drag-and-drop per personalizzare dashboard

**Task**:
- Implementare sistema widget
- Implementare drag-and-drop
- Salvare layout personalizzato per utente
- Widget configurabili (metriche, grafici, tabelle)

**File da creare/modificare**:
- `backend/models.py` (modello UserDashboard)
- `frontend/templates/dashboard.html` (widget system)

### Notifiche In-App
**Obiettivo**: Notifiche browser oltre alle email

**Task**:
- Implementare sistema notifiche in-app
- Integrare con alert esistenti
- Notifiche browser (Web Notifications API)
- Centro notifiche nella UI

**File da creare/modificare**:
- `backend/services/utils/notifications.py`
- `frontend/templates/` (centro notifiche)

### Audit Log Completo
**Obiettivo**: Log tutte le operazioni critiche con ricerca

**Task**:
- Creare modello DB per audit log
- Log operazioni critiche (creazione/modifica/eliminazione)
- Log accessi utente
- Log modifiche configurazione
- Interfaccia ricerca audit log
- Export audit log

**File da creare/modificare**:
- `backend/models.py` (modello AuditLog)
- `backend/services/utils/audit.py`
- `frontend/templates/settings_audit.html`

### Backup Automatico DB
**Obiettivo**: Strategia backup e restore

**Task**:
- Implementare backup automatico DB
- Configurare frequenza backup
- Configurare retention backup
- Implementare restore da backup
- Notifiche backup falliti

**File da creare/modificare**:
- `backend/scripts/backup.py`
- Configurazione scheduler per backup

### API Documentazione
**Obiettivo**: Swagger/OpenAPI completo

**Task**:
- Configurare FastAPI automatic docs
- Documentare tutti gli endpoint
- Aggiungere esempi richiesta/risposta
- Documentare modelli dati

**File da modificare**:
- `backend/main.py` (configurazione docs)
- Aggiungere docstring a tutti gli endpoint

### Test Automatizzati
**Obiettivo**: Unit test, integration test

**Task**:
- Setup framework test (pytest)
- Scrivere unit test per servizi
- Scrivere integration test per API
- Test coverage > 80%
- CI/CD integration

**File da creare**:
- `backend/tests/` (directory test)
- `pytest.ini` (configurazione)

### Monitoring e Metrics
**Obiettivo**: Prometheus, Grafana (opzionale)

**Task**:
- Integrare Prometheus metrics
- Dashboard Grafana
- Alerting su metriche
- Monitoring performance

**File da creare/modificare**:
- `backend/services/monitoring.py`
- Configurazione Prometheus/Grafana

---

## 📝 Note Implementazione

### Considerazioni Generali
- Mantenere coerenza con codice esistente
- Seguire best practices Python/FastAPI
- Documentare modifiche significative
- Testare in ambiente sviluppo prima di produzione
- Considerare backward compatibility

### Struttura File
- Backend: `backend/services/`
- Frontend: `frontend/templates/`
- Database: Migration Alembic in `backend/alembic/versions/`
- Configurazione: `backend/config.py`

### Dipendenze
- Verificare `requirements.txt` aggiornato
- Testare compatibilità versioni
- Documentare nuove dipendenze
