# 📋 TODO - Funzionalità Mancanti

## 🔴 PRIORITÀ ALTA

### 1. Grafici Performance nella Dashboard Analytics
**Stato**: Dashboard base completa, grafici mancanti

**Cosa serve**:
- ❌ Grafici trend (spend, conversioni nel tempo)
- ❌ Grafici distribuzione (per campagna, adset, ad)
- ❌ Heatmap performance
- ❌ Confronto periodi

**Librerie suggerite**: Chart.js, Plotly, o ApexCharts

**Endpoint**: `/analytics` (già esistente)

---

### 2. Export e Report
**Stato**: Non implementato

**Cosa serve**:
- ❌ **Export CSV/Excel** con dati combinati:
  - Dati lead (anagrafica, stato)
  - Dati marketing (campagna, adset, ad, metriche)
  - Storico lavorazioni Ulixe
- ❌ **Report periodici configurabili**:
  - Giornaliero, settimanale, mensile
  - Template personalizzabili
  - Invio automatico via email
- ❌ **Alert configurabili**:
  - CPL sopra soglia
  - Conversioni sotto soglia
  - Anomalie performance
  - Notifiche errori critici

**Endpoint da creare**: 
- `/api/export/csv`
- `/api/export/excel`
- `/api/reports` (CRUD report)
- `/api/alerts` (configurazione alert)

---

## 🟡 PRIORITÀ MEDIA

### 3. Logica Selezione Lead per Ulixe
**Stato**: Implementazione base (esclude solo "NO CRM" e rifiutate)

**Cosa migliorare**:
- ⚠️ Criteri più sofisticati:
  - Data ultimo check (non controllare troppo spesso)
  - Stato attuale (priorità per alcuni stati)
  - Età lead (lead troppo vecchie?)
- ⚠️ Finestra temporale:
  - Max 1 mese per batch (per query molto grosse)
  - Query singole: nessun limite temporale

**File da modificare**: `services/sync/ulixe_sync.py`

---

### 4. Update Magellano con Stati Ulixe
**Stato**: Non implementato (da fare quando necessario)

**Cosa serve**:
- ❌ Metodo `update_lead_status()` in `MagellanoService`
- ❌ Mapping stati Ulixe → valori Magellano
- ❌ Integrazione nel flusso scheduler (quando necessario)

**Nota**: Da implementare solo se serve effettivamente aggiornare Magellano

**File da modificare**: `services/integrations/magellano.py`

---

## 🟢 PRIORITÀ BASSA

### 5. Settings Avanzati Configurabili
**Stato**: Non implementato

**Cosa serve**:
- ❌ Sezione `/settings/advanced`:
  - Configurazione scheduler (orari, frequenze)
  - Configurazione rate limiting
  - Configurazione retention dati
  - Configurazione notifiche/alert
- ❌ Rimuovere hardcoding da backend
- ❌ Spostare configurazioni in DB
- ❌ Interfaccia per operatori non tecnici
- ❌ Validazione configurazioni

**Modelli DB da creare**: `Configuration`, `SchedulerConfig`, `RateLimitConfig`

---

### 6. Multi-tenant Configurabile
**Stato**: Preparazione futura

**Cosa serve**:
- ❌ Gestione brand/corsi multipli
- ❌ Isolamento dati per tenant
- ❌ Configurazione per tenant
- ❌ Sistema di ruoli per tenant

**Nota**: Da implementare quando necessario

**Modelli DB da modificare**: Aggiungere `tenant_id` a tutte le tabelle principali

---

### 7. Ottimizzazioni Performance
**Stato**: Non implementato

**Cosa serve**:
- ❌ Batch processing per grandi volumi
- ❌ Caching dati Meta (evitare chiamate duplicate)
- ❌ Retry logic con exponential backoff
- ❌ Circuit breaker per servizi esterni
- ❌ Indicizzazione DB per query veloci
- ❌ Background jobs per operazioni pesanti

**Librerie suggerite**: 
- Redis per caching
- Celery per background jobs
- Tenacity per retry logic

---

## 📊 PRIORITÀ SUGGERITA

### Sprint Immediato (1-2 settimane)
1. ✅ ~~Correlazione Automatica Lead ↔ Marketing~~ (Completato)
2. ✅ ~~Vista Dettaglio Lead Estesa~~ (Completato)
3. 🔄 **Grafici Analytics** (trend, distribuzione, heatmap)
4. 🔄 **Export CSV/Excel** (dati combinati)

### Sprint Breve Termine (1 mese)
5. **Report Periodici** (configurabili, template)
6. **Alert Configurabili** (soglie, notifiche)
7. **Logica Selezione Lead Migliorata** (criteri sofisticati)

### Sprint Medio Termine (2-3 mesi)
8. **Update Magellano** (solo se serve)
9. **Settings Avanzati** (configurazione completa)
10. **Ottimizzazioni Performance** (batch, caching, retry)

### Sprint Lungo Termine (quando necessario)
11. **Multi-tenant** (quando necessario)

---

## ❓ DOMANDE APERTE DA RISOLVERE

1. **Update Magellano**:
   - Serve effettivamente aggiornare Magellano con stati Ulixe?
   - Quale API/metodo usare per l'update?

2. **Configurazione**:
   - Chi gestirà le configurazioni? (ruolo minimo richiesto?)
   - Serve audit log delle modifiche configurazione?

3. **Multi-tenant**:
   - Quando si prevede l'uso multi-tenant?
   - Quali sono i criteri di isolamento? (per brand, per corso, altro?)

4. **Backup**:
   - Frequenza e retention?
   - Strategia di backup automatico?

---

## 📝 NOTE TECNICHE

### Grafici Analytics
- Considerare libreria leggera per non appesantire il frontend
- Chart.js: semplice, leggero, buona documentazione
- Plotly: più potente, ma più pesante
- ApexCharts: buon compromesso

### Export CSV/Excel
- Usare `pandas` per manipolazione dati
- Usare `openpyxl` per Excel
- Considerare streaming per grandi volumi

### Performance
- Implementare caching con TTL appropriato
- Usare indici DB per query frequenti
- Considerare paginazione per grandi dataset

---

## 🎯 PROSSIMI PASSI IMMEDIATI

1. **Aggiungere Grafici Analytics**
   - Scegliere libreria grafici (Chart.js consigliato)
   - Implementare grafici trend nella dashboard `/analytics`
   - Implementare grafici distribuzione

2. **Implementare Export CSV/Excel**
   - Endpoint `/api/export/csv` con filtri
   - Endpoint `/api/export/excel` con filtri
   - Template frontend per download

3. **Migliorare Logica Selezione Lead**
   - Aggiungere criteri di selezione più sofisticati
   - Implementare finestra temporale configurabile

---

## 🆕 NUOVE RICHIESTE - ANALISI E SOLUZIONI

### A) Nuove Maschere: Lavorazioni e Marketing

#### A.1 - Maschera Lavorazioni
**Obiettivo**: Vista dedicata che mostra solo dati sulle lavorazioni (stati Ulixe)

**Stato**: ✅ Implementato - ⚠️ DA TESTARE

**Cosa serve**:
- ✅ Nuova pagina `/lavorazioni` - ✅ Implementato
- ✅ Filtri per:
  - Stato lavorazione (in lavorazione, rifiutato, crm, finale) - ✅ Implementato
  - Periodo (data creazione, ultimo check) - ✅ Implementato
  - Campagna/Account - ✅ Implementato
  - Ricerca (nome, email, telefono) - ✅ Implementato
- ✅ Tabella con colonne:
  - Lead info (nome, cognome, email, telefono) - ✅ Implementato
  - Stato attuale - ✅ Implementato
  - Data ultimo check - ✅ Implementato
  - Storico stati (timeline) - ✅ Implementato
  - Campagna di provenienza - ✅ Implementato
- ✅ Statistiche aggregate:
  - Totale in lavorazione - ✅ Implementato
  - Totale rifiutate - ✅ Implementato
  - Totale CRM - ✅ Implementato
  - Tasso conversione - ✅ Implementato

**Endpoint creato**: `/lavorazioni` (GET con filtri) - ✅ Implementato

**Query DB**: 
```sql
SELECT * FROM leads 
WHERE status_category IN ('in_lavorazione', 'crm', 'finale', 'rifiutato')
-- con filtri dinamici
```

**Considerazioni**:
- Separare questa vista dalla dashboard principale per focus specifico
- Potrebbe essere utile anche un export dedicato per lavorazioni
- Considerare grafici trend per stati lavorazione nel tempo

---

#### A.2 - Maschera Marketing (Struttura Gerarchica)
**Obiettivo**: Vista gerarchica Campagne → Adset → Creatività con metriche aggregate

**Stato**: ✅ Implementato - ⚠️ DA TESTARE

**Cosa serve**:
- ✅ Nuova pagina `/marketing` - ✅ Implementato
- ✅ **Struttura gerarchica con dropdown**:
  - **Livello 1**: Lista campagne (dropdown principale) - ✅ Implementato
  - **Livello 2**: Adset della campagna selezionata (dropdown secondario) - ✅ Implementato
  - **Livello 3**: Creatività dell'adset selezionato (dropdown terziario) - ✅ Implementato
- ✅ **Dati esposti per ogni livello**:
  - **Numero lead + CPL Meta**: Lead totali e costo per lead da Meta - ✅ Implementato
  - **Numero entrati in campagna + CPL Magellano**: Lead che sono entrate in Magellano e relativo CPL - ✅ Implementato
  - **Numero + CPL Ulixe**: Lead processate da Ulixe e relativo CPL - ✅ Implementato
  - **Tabella con tre stati lavorazione**:
    - NO CRM (lead non ancora in lavorazione) - ✅ Implementato
    - Lavorazioni (in lavorazione) - ✅ Implementato
    - OK (completate/convertite) - ✅ Implementato

**Endpoint creati**: 
- `/api/marketing/campaigns` (lista campagne) - ✅ Implementato
- `/api/marketing/campaigns/{id}/adsets` (adsets per campagna) - ✅ Implementato
- `/api/marketing/adsets/{id}/ads` (creatività per adset) - ✅ Implementato

**Query DB complesse**:
```sql
-- Aggregazione per campagna
SELECT 
  mc.campaign_name,
  COUNT(DISTINCT l.id) as total_leads,
  SUM(mmd.spend) / COUNT(DISTINCT l.id) as cpl_meta,
  -- ... altre metriche
FROM meta_campaigns mc
LEFT JOIN leads l ON l.meta_campaign_id = mc.id
LEFT JOIN meta_marketing_data mmd ON mmd.campaign_id = mc.id
GROUP BY mc.id
```

**Considerazioni**:
- Usare AJAX per caricare adset/creatività on-demand (lazy loading)
- Caching dei dati aggregati per performance
- Considerare paginazione per campagne numerose
- Filtri avanzati: periodo, account Meta, tag campagne

**UI/UX**:
- Dropdown cascata (campagna → adset → creatività)
- Card con metriche principali sempre visibili
- Tabella dettagliata espandibile
- Grafici comparativi (CPL Meta vs CPL Magellano vs CPL Ulixe)

---

### B) Settings Piattaforma - Riorganizzazione

**Obiettivo**: Creare nuovo sotto-menu "Settings Piattaforma", spostare utenti dentro, accesso solo super-admin

**Stato**: ✅ Implementato - ⚠️ DA TESTARE

**Cosa serve**:
- ✅ Nuovo menu item "Settings Piattaforma" nel menu principale (solo super-admin)
- ✅ Spostare sezione utenti da `/settings/users` a `/settings/platform/users`
- ✅ **Accesso solo super-admin**:
  - Helper function `require_super_admin()` su tutti gli endpoint `/settings/platform/*`
  - Redirect se ruolo non super-admin
  - Nascondere menu item se non super-admin
- ✅ **Whitelist automatica**:
  - Solo utenti registrati nel DB sono in whitelist per accesso (già implementato in `auth.py`)
  - Login Google OAuth verifica presenza in DB prima di autorizzare

**Modifiche necessarie**:
- ✅ `backend/services/api/auth.py`: Verifica utente in DB invece di whitelist hardcoded (già implementato)
- ✅ `backend/services/api/ui.py`: Spostare endpoint utenti e aggiungere check super-admin
- ✅ `frontend/templates/base.html`: Aggiungere menu item "Settings Piattaforma" (solo per super-admin)
- ✅ `frontend/templates/settings_users.html`: Creato nuovo template `settings_platform_users.html`

**Considerazioni**:
- Mantenere compatibilità con ruoli esistenti (admin, viewer)
- Audit log per modifiche utenti (chi ha fatto cosa)
- Possibilità di aggiungere altre sezioni sotto "Settings Piattaforma" in futuro:
  - Configurazioni sistema
  - Logs applicazione
  - Backup/restore

**Struttura menu suggerita**:
```
Settings
├── Campaigns (tutti gli admin)
├── Meta Accounts (tutti gli admin)
├── Meta Campaigns (tutti gli admin)
└── Piattaforma (solo super-admin)
    └── Utenti
```

---

### C) Ingestion Campagne Meta - Miglioramenti UI

#### C.1 - Vista Globale con Filtro Tag
**Obiettivo**: Semplificare vista campagne, mostrare solo numero totale con filtro tag

**Cosa serve**:
- ❌ Modificare `/settings/meta-campaigns`:
  - Rimuovere lista dettagliata campagne (o renderla opzionale)
  - Mostrare card con metriche aggregate:
    - Totale campagne
    - Totale adset
    - Totale creatività
    - Spesa totale
    - Lead totali
- ❌ **Filtro tag**:
  - Dropdown/multi-select per filtrare per tag
  - Tag da `MetaCampaign.tags` (se presente) o da `MetaCampaign.campaign_name` (parsing)
  - Aggiornamento metriche in real-time al cambio filtro

**Endpoint da modificare**: `/api/meta-campaigns/stats` (con filtro tag)

**Considerazioni**:
- Se tag non esistono nel DB, creare sistema di tagging
- Considerare auto-tagging basato su pattern nel nome campagna
- Export dati filtrati per tag

---

#### C.2 - Pulsante Sync Forzato
**Obiettivo**: Aggiungere pulsante per forzare nuova sync manuale

**Cosa serve**:
- ❌ Pulsante "Sync Now" nella pagina `/settings/meta-campaigns`
- ❌ Endpoint `/api/meta-campaigns/sync` (POST)
- ❌ Background task che esegue `meta_marketing_sync_job`
- ❌ Feedback UI:
  - Loading state durante sync
  - Notifica successo/errore
  - Timestamp ultima sync

**Endpoint esistente da riutilizzare**: `/settings/meta-accounts/sync` (adattare per campagne)

**Considerazioni**:
- Prevenire sync multiple simultanee (lock)
- Mostrare progress se possibile
- Log sync manuali vs automatiche

---

#### C.3 - Allineamento Pulsante Filtro
**Obiettivo**: Fix problemi di allineamento UI pulsante filtro

**Cosa serve**:
- ❌ Review CSS/Tailwind per allineamento
- ❌ Test responsive su diversi dispositivi
- ❌ Fix layout form filtri

**File da modificare**: `frontend/templates/settings_meta_campaigns.html`

---

#### C.4 - Pagina Dettaglio Account
**Obiettivo**: Creare pagina per vedere dettagli account con lista campagne

**Cosa serve**:
- ❌ Nuova pagina `/settings/meta-accounts/{account_id}`
- ❌ Dettagli account:
  - Nome account
  - Account ID
  - Token status (valido/scaduto)
  - Ultima sync
  - Statistiche aggregate
- ❌ Lista campagne dell'account:
  - Tabella con tutte le campagne
  - Filtri e ricerca
  - Link a dettaglio campagna (se necessario)

**Endpoint da creare**: `/api/meta-accounts/{account_id}` (GET)

**Considerazioni**:
- Paginazione per account con molte campagne
- Export campagne per account
- Possibilità di disabilitare sync per singolo account

---

### D) Ingestion Magellano - Upload CSV/ZIP e Sync per Campagna

#### D.1 - Pagina Upload CSV/ZIP
**Obiettivo**: Creare pagina dedicata per upload file Magellano con gestione password dinamica

**Stato**: ✅ Implementato - ⚠️ DA TESTARE

**Cosa serve**:
- ✅ Nuova pagina `/settings/magellano/upload` - ✅ Implementato
- ✅ Form upload:
  - Input file (accetta .zip, .xls, .xlsx, .csv) - ✅ Implementato
  - Input data (per calcolo password: `ddmmyyyyT-Direct`) - ✅ Implementato
  - Validazione file - ✅ Implementato
- ✅ Processing backend:
  - Estrazione ZIP (se necessario) con password calcolata - ✅ Implementato
  - Parsing file Excel/CSV - ✅ Implementato
  - Salvataggio dati in DB - ✅ Implementato
  - Feedback successo/errore - ✅ Implementato

**Endpoint creato**: 
- `/api/magellano/upload` (POST, multipart/form-data) - ✅ Implementato
- Utilizza `MagellanoService.process_uploaded_file()` - ✅ Implementato

**Considerazioni**:
- Validazione formato file
- Gestione errori password errata
- Progress bar per file grandi
- Log upload manuali

**Password dinamica**:
```python
def generate_password(date: date) -> str:
    return date.strftime("%d%m%Y") + "T-Direct"
```

---

#### D.2 - Sync Automatica per Singola Campagna
**Obiettivo**: Possibilità di lanciare sync automatica da frontend per singola campagna (non globale)

**Cosa serve**:
- ❌ Nuova pagina `/settings/magellano/sync` o sezione in upload
- ❌ Form:
  - Dropdown/input per ID campagna
  - Date range (start_date, end_date)
  - Pulsante "Sync Campagna"
- ❌ Endpoint `/api/magellano/sync/campaign` (POST)
- ❌ Background task che esegue `run_magellano_sync()` per singola campagna

**Endpoint esistente da riutilizzare**: `/sync` (adattare per singola campagna)

**Considerazioni**:
- Validazione ID campagna esistente
- Feedback progress sync
- Possibilità di sync multiple campagne (checkbox multi-select)
- Log sync manuali vs automatiche

**File da modificare**: 
- `backend/services/api/ui.py`: Aggiungere endpoint sync per campagna
- `frontend/templates/`: Creare template upload/sync Magellano

---

### E) Analisi Cosa Manca Ancora

**Brainstorming**:
- ✅ Maschere lavorazioni e marketing → **Aggiunto in A**
- ✅ Settings piattaforma → **Aggiunto in B**
- ✅ Ingestion campagne miglioramenti → **Aggiunto in C**
- ✅ Ingestion Magellano upload/sync → **Aggiunto in D**
- ❌ **Sistema alert email** → **Aggiunto in F**
- ❌ **Maschere sync forzate Meta/Ulixe** → **Aggiunto in G, H**
- ❌ **Healthcheck e restart automatico** → **Aggiunto in I**
- ❌ **Validazione Python come linguaggio** → **Aggiunto in L**
- ❌ **Confronto con lista sviluppo** → **Aggiunto in M**

**Altre considerazioni**:
- Dashboard principale potrebbe beneficiare di widget riassuntivi
- Sistema di notifiche in-app (oltre alle email)
- Audit log completo per tutte le operazioni critiche
- Backup automatico configurazioni

---

### F) Sistema Alert Email

**Obiettivo**: Impostare sistema di alert email per ingestion dati (Magellano, Ulixe, Meta)

**Stato**: ✅ Implementato - ⚠️ DA TESTARE

**Cosa serve**:
- ✅ **Configurazione SMTP**:
  - Aggiungere variabili ambiente per SMTP (host, port, user, password) - ✅ Implementato
  - Libreria: `smtplib` (built-in) - ✅ Implementato
- ✅ **Template email**:
  - Template HTML per alert - ✅ Implementato
  - Template per successo sync - ✅ Implementato
  - Template per errori critici - ✅ Implementato
- ✅ **Alert per ingestion Magellano**:
  - Successo: numero lead importate - ✅ Implementato
  - Errore: dettagli errore, campagna interessata - ✅ Implementato
- ✅ **Alert per ingestion Ulixe**:
  - Successo: numero lead controllate, numero aggiornate - ✅ Implementato
  - Errore: lead con errori, dettagli - ✅ Implementato
- ✅ **Alert per ingestion Meta**:
  - Successo: account sincronizzati, campagne aggiornate - ✅ Implementato
  - Errore: account con errori, dettagli API - ✅ Implementato

**Endpoint creati**: 
- `/api/alerts` (POST) - Salva configurazione alert - ✅ Implementato
- `/api/alerts/test` (POST) - Test invio email - ✅ Implementato
- `/settings/alerts` - Pagina gestione configurazioni - ✅ Implementato

**Modello DB creato**:
- `AlertConfig` - ✅ Implementato
- Migration `add_alert_configs_table.py` - ✅ Creata

**Considerazioni**:
- Rate limiting email (non spammare)
- Queue email per non bloccare sync
- Template personalizzabili
- Possibilità di disabilitare alert per tipo

**Librerie suggerite**:
- `emails` o `smtplib` per invio
- `jinja2` per template email
- `celery` per queue (opzionale, se necessario)

---

### G) Maschera Ingestion Meta per Singolo Account

**Obiettivo**: Creare maschera dedicata per forzare sync Meta per singolo account pubblicitario

**Cosa serve**:
- ❌ Nuova pagina `/settings/meta-accounts/{account_id}/sync` o pulsante in dettaglio account
- ❌ Form/pulsante "Sync Now" per account specifico
- ❌ Endpoint `/api/meta-accounts/{account_id}/sync` (POST)
- ❌ Background task che esegue `MetaMarketingService.sync_account_campaigns()` per account specifico
- ❌ Feedback UI:
  - Loading state
  - Progress (se possibile)
  - Risultato sync (campagne aggiornate, errori)

**Endpoint esistente**: `/settings/meta-accounts/sync` (già presente, verificare se supporta singolo account)

**Considerazioni**:
- Prevenire sync multiple simultanee per stesso account
- Mostrare ultima sync e prossima sync programmata
- Log sync manuali
- Possibilità di schedulare sync ricorrente per account

**File da modificare**:
- `backend/services/api/ui.py`: Verificare/estendere endpoint sync account
- `frontend/templates/settings_meta_accounts.html`: Aggiungere pulsante sync per account

---

### H) Maschera Ingestion Ulixe

**Obiettivo**: Creare maschera per forzare sync Ulixe manualmente

**Cosa serve**:
- ❌ Nuova pagina `/settings/ulixe/sync` o sezione in settings
- ❌ Pulsante "Sync Now" per forzare sync Ulixe
- ❌ Opzioni avanzate (opzionali):
  - Filtro per lead specifiche (ID, campagna, stato)
  - Limite numero lead da controllare
- ❌ Endpoint `/api/ulixe/sync` (POST)
- ❌ Background task che esegue `ulixe_sync_job()`
- ❌ Feedback UI:
  - Statistiche sync (checked, updated, errors)
  - Tempo esecuzione
  - Lista errori (se presenti)

**Endpoint da creare**: `/api/ulixe/sync` (POST)

**Considerazioni**:
- Sync Ulixe può essere lenta (rate limiting 0.5s tra chiamate)
- Mostrare progress approssimativo
- Possibilità di interrompere sync (se necessario)
- Log sync manuali vs automatiche

**File da modificare**:
- `backend/services/api/ui.py`: Aggiungere endpoint sync Ulixe
- `frontend/templates/`: Creare template sync Ulixe

---

### I) Venv e Healthcheck con Restart Automatico

#### I.1 - Virtual Environment
**Obiettivo**: Impostare tutto applicativo dentro venv

**Cosa serve**:
- ❌ Verificare struttura progetto:
  - `requirements.txt` già presente ✅
  - Creare `venv/` o usare Docker (già presente ✅)
- ❌ **Se Docker**:
  - Verificare che Dockerfile usi venv o installazione diretta
  - Documentare setup venv locale per sviluppo
- ❌ **Se non Docker**:
  - Script `setup.sh` per creare venv e installare dipendenze
  - `.env.example` per variabili ambiente
  - Documentazione setup

**Considerazioni**:
- Docker già presente → venv gestito nel container
- Per sviluppo locale: creare venv separato
- `requirements.txt` aggiornato con tutte le dipendenze

---

#### I.2 - Healthcheck Esterno con Restart Automatico
**Obiettivo**: Sistema esterno che fa ping e restart in caso di crash

**Stato**: ✅ Implementato - ⚠️ DA TESTARE

**Cosa serve**:
- ✅ **Healthcheck endpoint**:
  - Endpoint `/health` (GET) - ✅ Implementato
  - Verifica: DB connesso - ✅ Implementato
  - Response: `{"status": "ok", "timestamp": "...", "checks": {...}}` - ✅ Implementato
- ❌ **Script esterno di monitoraggio**:
  - Script bash/Python che fa ping ogni X secondi
  - Se non risponde: restart applicazione
  - Log tentativi restart
- ❌ **Opzioni implementazione**:
  1. **Docker healthcheck** (se in Docker):
     ```dockerfile
     HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
       CMD curl -f http://localhost:8000/health || exit 1
     ```
  2. **Systemd service** (se su server Linux):
     - Service file con `Restart=always`
     - Healthcheck script separato
  3. **Supervisor** (process manager):
     - Configurazione supervisor
     - Auto-restart su crash
  4. **Script esterno cron**:
     - Cron job che controlla healthcheck
     - Restart via docker-compose o systemctl

**Endpoint da creare**: `/health` (GET)

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
- Healthcheck non deve essere troppo pesante (solo check base)
- Evitare restart loop infiniti (circuit breaker)
- Notifiche quando restart avviene
- Log dettagliati per debugging

**Librerie suggerite**:
- `psutil` per check risorse sistema (opzionale)
- `requests` per healthcheck HTTP

---

### L) Validazione Python come Linguaggio

**Obiettivo**: Valutare se Python è adatto per questo applicativo

**Analisi**:

**✅ PRO Python**:
- **Ecosistema ricco**: 
  - FastAPI: moderno, performante, async
  - SQLAlchemy: ORM maturo per DB
  - Playwright: automazione browser (Magellano)
  - APScheduler: scheduler affidabile
- **Integrazioni esistenti**:
  - Tutto già implementato in Python ✅
  - Client SOAP (Ulixe) funzionante
  - Meta API (Graph API) ben supportate
- **Sviluppo rapido**:
  - Prototipazione veloce
  - Codice leggibile
  - Community attiva
- **Performance adeguate**:
  - FastAPI è performante (comparabile a Node.js)
  - Async I/O per operazioni I/O bound
  - Background tasks per operazioni pesanti

**⚠️ CONSIDERAZIONI**:
- **CPU-intensive tasks**: Python non è ottimale per calcoli pesanti, ma questo progetto è I/O bound (API, DB, web scraping) → OK
- **Memory**: Python può usare più memoria di linguaggi compilati, ma per questo progetto è accettabile
- **Deployment**: Docker risolve problemi di dipendenze → OK

**✅ CONCLUSIONE**: 
Python è **perfettamente adatto** per questo applicativo perché:
1. Progetto già funzionante in Python ✅
2. Operazioni principalmente I/O bound (API, DB, web scraping)
3. Ecosistema maturo per tutte le necessità
4. Sviluppo e manutenzione più semplici
5. Team già competente in Python (presumibilmente)

**Raccomandazioni**:
- Continuare con Python
- Considerare ottimizzazioni se necessario (caching, async, background jobs)
- Monitorare performance in produzione

---

### M) Confronto con Lista Sviluppo Condivisa

**Confronto TODO.md originale vs nuove richieste**:

#### ✅ Già nella lista originale:
1. ✅ Grafici Analytics → **Priorità alta, già presente**
2. ✅ Export CSV/Excel → **Priorità alta, già presente**
3. ✅ Alert configurabili → **Priorità alta, già presente** (esteso con email in F)
4. ✅ Logica selezione lead Ulixe → **Priorità media, già presente**
5. ✅ Settings avanzati → **Priorità bassa, già presente**
6. ✅ Ottimizzazioni performance → **Priorità bassa, già presente**

#### 🆕 Nuove richieste aggiunte:
1. 🆕 **Maschera Lavorazioni** (A.1) → **Nuova, priorità alta**
2. 🆕 **Maschera Marketing gerarchica** (A.2) → **Nuova, priorità alta**
3. 🆕 **Settings Piattaforma** (B) → **Nuova, priorità media**
4. 🆕 **Miglioramenti UI Ingestion Campagne** (C) → **Nuova, priorità media**
5. 🆕 **Upload Magellano CSV/ZIP** (D.1) → **Nuova, priorità alta**
6. 🆕 **Sync Magellano per campagna** (D.2) → **Nuova, priorità media**
7. 🆕 **Alert Email** (F) → **Estensione alert esistenti, priorità alta**
8. 🆕 **Maschere sync forzate Meta/Ulixe** (G, H) → **Nuova, priorità media**
9. 🆕 **Healthcheck e restart** (I) → **Nuova, priorità alta (infrastruttura)**

#### 📊 Cosa manca ancora (brainstorming):

**Funzionalità mancanti potenziali**:
- ❌ **Dashboard widget personalizzabili**: Widget drag-and-drop
- ❌ **Notifiche in-app**: Oltre alle email, notifiche browser
- ❌ **Audit log completo**: Log tutte le operazioni critiche con ricerca
- ❌ **Backup automatico DB**: Strategia backup e restore
- ❌ **API documentazione**: Swagger/OpenAPI completo
- ❌ **Test automatizzati**: Unit test, integration test
- ❌ **Monitoring e metrics**: Prometheus, Grafana (opzionale)
- ❌ **Multi-lingua**: Se necessario in futuro
- ❌ **Mobile responsive**: Ottimizzazione mobile (già presente con Tailwind, verificare)

**Priorità suggerita nuove funzionalità**:
1. **Alta**: Maschere lavorazioni/marketing, upload Magellano, alert email, healthcheck
2. **Media**: Settings piattaforma, sync forzate, miglioramenti UI
3. **Bassa**: Widget personalizzabili, audit log avanzato, monitoring

---

## 📋 RIEPILOGO COMPLETO TODO

### Priorità Alta (Sprint Immediato)
1. Grafici Analytics
2. Export CSV/Excel
3. Maschera Lavorazioni (A.1)
4. Maschera Marketing gerarchica (A.2)
5. Upload Magellano CSV/ZIP (D.1)
6. Alert Email (F)
7. Healthcheck e restart (I.2)

### Priorità Media (Sprint Breve Termine)
8. Settings Piattaforma (B)
9. Miglioramenti UI Ingestion Campagne (C)
10. Sync Magellano per campagna (D.2)
11. Maschere sync forzate Meta/Ulixe (G, H)
12. Logica selezione lead migliorata

### Priorità Bassa (Sprint Medio Termine)
13. Settings avanzati configurabili
14. Ottimizzazioni performance
15. Update Magellano (se necessario)
16. Multi-tenant (quando necessario)

---

## 🎯 PROSSIMI PASSI IMMEDIATI (Aggiornato)

1. ✅ ~~**Implementare Healthcheck** (I.2)~~ - ⚠️ DA TESTARE
2. ✅ ~~**Creare Maschera Lavorazioni** (A.1)~~ - ⚠️ DA TESTARE
3. 🔄 **Implementare Upload Magellano** (D.1) - Funzionalità richiesta (IN CORSO)
4. **Creare Maschera Marketing** (A.2) - Funzionalità core
5. **Sistema Alert Email** (F) - Monitoring critico
6. **Grafici Analytics** - Visualizzazione dati
7. **Export CSV/Excel** - Funzionalità richiesta
