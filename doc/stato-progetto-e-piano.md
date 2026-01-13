# Stato Progetto e Piano di Sviluppo

## 📊 STATO ATTUALE - Cosa è stato fatto

### ✅ Completato

#### 1. **Autenticazione e Autorizzazione**
- ✅ Google OAuth integrato
- ✅ Sistema whitelist utenti
- ✅ Gestione ruoli (viewer, admin, super-admin)
- ✅ Interfaccia gestione utenti (settings/users)

#### 2. **Database e Modelli**
- ✅ Modello `User` con ruoli e id_sede
- ✅ Modello `Lead` con tutti i campi necessari
- ✅ Modello `LeadHistory` per tracking storico stati
- ✅ Modello `ManagedCampaign` per campagne gestite
- ✅ Modello `SyncLog` per log sincronizzazioni
- ✅ Enum `StatusCategory` per categorizzazione stati

#### 3. **Integrazione Magellano**
- ✅ Service `MagellanoService` completo
- ✅ Automazione Playwright per download dati
- ✅ Parsing Excel e mapping campi
- ✅ Gestione password dinamica ZIP
- ✅ Endpoint sync manuale da dashboard

#### 4. **Integrazione Ulixe**
- ✅ Client SOAP con zeep
- ✅ Metodo `get_lead_status()` implementato
- ✅ Categorizzazione automatica stati
- ✅ Gestione errori e timeout

#### 5. **Integrazione Meta**
- ✅ Service `MetaService` per Conversion API
- ✅ Service `MetaMarketingService` per ingestion dati marketing
- ✅ Invio eventi CAPI (LeadStatusChange) integrato nello scheduler
- ✅ Hash automatico email/telefono (gestito da SDK)
- ✅ Modelli DB completi per account/campagne/ads/metriche
- ✅ Interfaccia configurazione account e campagne
- ✅ Sincronizzazione automatica dati marketing

#### 6. **Scheduler**
- ✅ **Completo**: Scheduler sequenziale implementato
  - ✅ Configurato per 00:30
  - ✅ Pipeline sequenziale concatenata:
    1. Magellano: recupera e salva dati in DB
    2. Ulixe: sync per tutte le lead non rifiutate (status_category != RIFIUTATO)
    3. Meta Marketing: ingestion dati marketing
    4. Meta Conversion API: invia eventi per stati aggiornati
  - ✅ Rate limiting 0.5s tra chiamate Ulixe
  - ✅ Logging dettagliato per ogni step
  - ✅ Gestione errori per ogni fase

#### 7. **Frontend**
- ✅ Dashboard base con statistiche
- ✅ Tabella lead recenti
- ✅ Form sync manuale Magellano
- ✅ Interfaccia gestione campagne (settings/campaigns)
- ✅ Interfaccia gestione account Meta (settings/meta-accounts)
- ✅ Interfaccia gestione campagne Meta (settings/meta-campaigns)
- ✅ Dashboard Analytics 360° (analytics) con correlazione marketing ↔ feedback
- ✅ Design moderno con Tailwind CSS
- ✅ **Riorganizzazione struttura**: Separato frontend da backend (`frontend/` directory)

#### 8. **API REST**
- ✅ Endpoint CRUD leads (`/api/leads`)
- ✅ Endpoint check Ulixe manuale
- ✅ Filtri e paginazione

#### 9. **Architettura e Organizzazione Codice**
- ✅ **Riorganizzazione services/**: Separato in 3 directory chiare
  - ✅ `api/` - FastAPI routers e endpoints
  - ✅ `integrations/` - Servizi integrazioni esterne (Magellano, Ulixe, Meta)
  - ✅ `sync/` - 4 job autonomi separati (magellano, ulixe, meta_marketing, meta_conversion)
- ✅ **SyncOrchestrator**: Gestione esecuzione sequenziale job
- ✅ **Separazione frontend/backend**: Directory `frontend/` separata con static/ e templates/
- ✅ **Docker**: Build context aggiornato per includere frontend nell'immagine
- ✅ **Seeders**: Sistema seeding per campagne Magellano
- ✅ **Documentazione**: README.md in services/ e frontend/

---

## ❌ COSA MANCA

### 🔴 Critico - Funzionalità Core

1. **Update Magellano con Stati Ulixe**
   - ❌ Logica per aggiornare Magellano con stati da Ulixe
   - ❌ Mapping stati Ulixe → valori Magellano
   - ⚠️ Da implementare quando necessario

2. **Logica Selezione Lead per Ulixe**
   - ⚠️ Attualmente: tutte le lead non rifiutate (status_category != RIFIUTATO)
   - ⚠️ Da definire meglio: quali lead richiamare a Ulixe e quali no
   - ⚠️ Possibili criteri: data ultimo check, stato attuale, etc.

3. **Gestione Finestra Temporale**
   - ⚠️ Attualmente: check tutte le lead non rifiutate
   - ⚠️ Da implementare: max 1 mese per batch (per query molto grosse)
   - ⚠️ Query singole: nessun limite temporale

### 🟡 Importante - Miglioramenti e Ottimizzazioni

4. **Correlazione Automatica Lead ↔ Marketing** ✅
   - ✅ Modelli DB pronti (meta_campaign_id, meta_adset_id, meta_ad_id in Lead)
   - ✅ Logica automatica implementata (`LeadCorrelationService`)
   - ✅ Strategia: Match usando campi Facebook da Magellano:
     - `facebook_campaign_name` → `MetaCampaign.name`
     - `facebook_ad_set` → `MetaAdSet.name`
     - `facebook_ad_name` → `MetaAd.name`
     - `facebook_id` → `MetaAd.ad_id` (priorità)
   - ✅ Integrata nel sync job Magellano

5. **Vista Dettaglio Lead Estesa** ✅
   - ✅ Pagina `/leads/{id}` implementata
   - ✅ Dati anagrafici lead
   - ✅ Storico lavorazioni Ulixe completo
   - ✅ Dati marketing correlati (campagna, adset, ad)
   - ✅ Metriche marketing (spend, impressions, clicks, CPL, etc.)
   - ✅ **Due livelli di analisi**:
     - **Livello 1**: Overview per `msg_id` (statistiche aggregate e lead correlate)
     - **Livello 2**: Overview per campagne Meta (statistiche aggregate, metriche marketing, timeline)
   - ⚠️ Grafici performance: DA IMPLEMENTARE (trend, distribuzione)

6. **Export e Report**
   - ❌ Export CSV/Excel con dati combinati (marketing + lavorazioni)
   - ❌ Report periodici configurabili
   - ❌ Alert configurabili (es. CPL sopra soglia)

### 🟢 Opzionale - Future Funzionalità

7. **Settings Avanzati Configurabili**
   - ❌ Sezione `/settings/advanced`
     - Configurazione scheduler (orari, frequenze)
     - Configurazione rate limiting
     - Configurazione retention dati
     - Configurazione notifiche/alert
   - ❌ Multi-tenant configurabile (preparazione futura)
     - Isolamento dati per tenant

8. **Ottimizzazioni Performance**
   - ❌ Batch processing per grandi volumi
   - ❌ Caching dati Meta (evitare chiamate duplicate)
   - ❌ Retry logic con exponential backoff
   - ❌ Circuit breaker per servizi esterni

---

## 🎯 PIANO DI SVILUPPO AGGIORNATO

### FASE 1: Completamento Funzionalità Core (Priorità Alta) ✅ COMPLETATA

#### 1.1 Fix Bug e Completamento Scheduler ✅
- [x] Fixato bug `user_id` → ora usa `external_user_id`
- [x] Completata logica scheduler per 00:30
- [x] Implementato flusso completo sequenziale:
  1. ✅ Fetch Magellano (lead giorno precedente) → Salvataggio DB con stato "inviate WS Ulixe"
  2. ✅ Check Ulixe per tutte le lead non rifiutate
  3. ✅ Update DB con nuovi stati
  4. ✅ Ingestion Meta Marketing
  5. ✅ Meta Conversion API per stati aggiornati
- [x] Gestione rate limiting (0.5s delay)
- [x] Logging dettagliato per ogni step
- [x] Error handling completo per ogni fase

#### 1.2 Update Magellano con Stati Ulixe ⚠️ DA FARE
- [ ] Implementare metodo update in `MagellanoService`
- [ ] Mapping stati Ulixe → valori Magellano
- [ ] Integrazione nel flusso scheduler (quando necessario)

---

### FASE 2: Integrazione Meta Marketing (Priorità Alta) ✅ COMPLETATA

#### 2.1 Modelli Database per Marketing ✅
- [x] Modello `MetaAccount` (account pubblicitari)
- [x] Modello `MetaCampaign` (campagne)
- [x] Modello `MetaAdSet` (gruppi inserzioni)
- [x] Modello `MetaAd` (singole inserzioni/creatività)
- [x] Modello `MetaMarketingData` (metriche giornaliere)
- [x] Relazioni con `Lead` (meta_campaign_id, meta_adset_id, meta_ad_id)
- [x] Migration creata (`add_meta_marketing_models.py`)

#### 2.2 Service Meta Marketing API ✅
- [x] Service `MetaMarketingService` per ingestion
- [x] Metodi per:
  - [x] Test connessione account
  - [x] Lista account disponibili
  - [x] Lista campagne (con filtri tag/nome)
  - [x] Lista adset per campagna
  - [x] Lista ads per adset
  - [x] Metriche marketing (insights: spend, impressions, clicks, conversions, etc.)
- [x] Gestione rate limiting Meta API
- [x] Formattazione valori con virgola decimale (formato italiano)

#### 2.3 Configurazione Front-End Account/Campagne ✅
- [x] Pagina `/settings/meta-accounts`
  - [x] Lista account configurati
  - [x] Form aggiunta account (token, account_id)
  - [x] Test connessione automatico
  - [x] Attivazione/disattivazione account
  - [x] Sincronizzazione manuale
- [x] Pagina `/settings/meta-campaigns`
  - [x] Lista campagne per account
  - [x] Filtri configurabili:
    - [x] Per tag
    - [x] Per nome (pattern matching)
    - [x] Per stato (attive/pause)
  - [x] Selezione campagne da sincronizzare
  - [x] Configurazione filtri via modal
- [x] Scheduler integrato per sync automatica dati marketing (STEP 3)

#### 2.4 Sincronizzazione Dati Marketing ✅
- [x] Job scheduler integrato nello scheduler principale (STEP 3)
- [x] Salvataggio metriche giornaliere in DB
- [x] Gestione aggiornamenti incrementali
- ⚠️ Correlazione automatica con lead: DA IMPLEMENTARE (vedi FASE 3)

---

### FASE 3: Interfaccia Correlazione Marketing ↔ Feedback (Parzialmente Completata)

#### 3.1 Vista Lead Dettaglio Estesa ✅ COMPLETATA
- [x] Pagina `/leads/{id}` implementata
- [x] Dati anagrafici lead
- [x] Storico lavorazioni Ulixe completo
- [x] Dati marketing correlati:
  - Campagna di origine
  - Adset/Ad specifica
  - Metriche marketing (spend, impressions, clicks, CPL, etc.)
  - Timeline metriche marketing (ultimi 30 giorni)
- [x] **Due livelli di analisi**:
  - **Livello 1**: Overview per `msg_id` (statistiche aggregate, lead correlate)
  - **Livello 2**: Overview per campagne Meta (statistiche aggregate, metriche marketing, timeline)
- [ ] Grafici performance: DA IMPLEMENTARE (trend, distribuzione)

#### 3.2 Dashboard Analytics 360° ✅ COMPLETATA
- [x] Nuova sezione `/analytics`
- [x] Metriche aggregate:
  - [x] Spend totale
  - [x] Impressions
  - [x] Tasso conversione
  - [x] Costo per lead (CPL)
- [x] Filtri avanzati:
  - [x] Per account
  - [x] Per campagna
  - [x] Per periodo (date from/to)
- [x] Tabella lead con dati marketing correlati
- ⚠️ Grafici: DA IMPLEMENTARE (trend, distribuzione, heatmap)

#### 3.3 Export e Report ❌ DA FARE
- [ ] Export CSV/Excel con dati combinati
- [ ] Report periodici configurabili
- [ ] Alert configurabili (es. CPL sopra soglia)

#### 3.4 Correlazione Automatica Lead ↔ Marketing ✅ COMPLETATA
- [x] Logica per correlare automaticamente lead con dati marketing
- [x] Strategia implementata:
  - Match usando `facebook_campaign_name` → `MetaCampaign.name`
  - Match usando `facebook_ad_set` → `MetaAdSet.name`
  - Match usando `facebook_ad_name` → `MetaAd.name`
  - Match usando `facebook_id` → `MetaAd.ad_id` (priorità)
- [x] Popolamento automatico di meta_campaign_id, meta_adset_id, meta_ad_id in Lead
- [x] Integrata nel sync job Magellano (`magellano_sync.py`)

---

### FASE 4: Sistema Configurabile Front-End (Priorità Media)

#### 4.1 Settings Avanzati
- [ ] Sezione `/settings/advanced`
  - Configurazione scheduler (orari, frequenze)
  - Configurazione rate limiting
  - Configurazione retention dati
  - Configurazione notifiche/alert
- [ ] Multi-tenant configurabile (preparazione futura)
  - Gestione brand/corsi multipli
  - Isolamento dati per tenant

#### 4.2 Configurazione Dinamica
- [ ] Rimuovere hardcoding da backend
- [ ] Spostare configurazioni in DB
- [ ] Interfaccia per operatori non tecnici
- [ ] Validazione configurazioni

---

## 📋 PRIORITÀ E TIMELINE SUGGERITA

### ✅ Sprint 1 (Completato)
1. ✅ Fix bug `user_id` in Lead → usa `external_user_id`
2. ✅ Completamento scheduler 00:30 con pipeline sequenziale
3. ⚠️ Update Magellano con stati Ulixe: DA FARE quando necessario

### ✅ Sprint 2 (Completato)
1. ✅ Modelli DB Meta Marketing
2. ✅ Service Meta Marketing API completo
3. ✅ Configurazione account Meta (front-end)
4. ✅ Migration database creata

### ✅ Sprint 3 (Completato)
1. ✅ Configurazione campagne con filtri
2. ✅ Sincronizzazione automatica dati marketing (STEP 3 scheduler)
3. ✅ Meta Conversion API integrata (STEP 4 scheduler)
4. ✅ Dashboard analytics 360° base

### 🔄 Sprint 4 (In Corso)
1. ⚠️ Correlazione automatica lead ↔ marketing (DA DEFINIRE strategia)
2. ⚠️ Vista dettaglio lead estesa
3. ⚠️ Grafici nella dashboard analytics
4. ⚠️ Export e report

### 📅 Sprint 5 (Futuro)
1. ⚠️ Logica selezione lead per Ulixe (da definire meglio)
2. ⚠️ Gestione finestra temporale (max 1 mese per batch)
3. ⚠️ Settings avanzati configurabili
4. ⚠️ Multi-tenant
5. ⚠️ Ottimizzazioni e polish

---

## 🔧 CONSIDERAZIONI TECNICHE

### Meta Marketing API
- **Endpoint**: Graph API v18+ (o versione corrente)
- **Autenticazione**: System User Token (già disponibile)
- **Rate Limiting**: 
  - 200 calls/hour per user token
  - Usare Batch API quando possibile
- **Campi da recuperare**:
  - Account: name, account_id
  - Campaign: name, id, status, objective, daily_budget, lifetime_budget
  - AdSet: name, id, campaign_id, targeting, optimization_goal
  - Ad: name, id, adset_id, creative (thumbnail_url, etc.)
  - Insights: spend, impressions, clicks, conversions, ctr, cpc, etc.

### Correlazione Lead ↔ Marketing
- **Strategia 1**: UTM parameters in Magellano
- **Strategia 2**: Campaign ID matching
- **Strategia 3**: Facebook Click ID (fbclid) se disponibile
- **Strategia 4**: Timestamp + IP matching (meno affidabile)

### Performance
- Batch processing per grandi volumi
- Caching dati Meta (evitare chiamate duplicate)
- Indicizzazione DB per query veloci
- Background jobs per operazioni pesanti

---

## ❓ DOMANDE APERTE

1. **Meta Marketing**:
   - Quali metriche sono prioritarie?
   - Frequenza sync desiderata? (giornaliera, oraria?)
   - Storico dati: quanto indietro recuperare?

2. **Correlazione**:
   - Come vengono tracciate le lead da Meta? (UTM, pixel, altro?)
   - C'è un campo in Magellano che identifica la campagna Meta?

3. **Configurazione**:
   - Chi gestirà le configurazioni? (ruolo minimo richiesto?)
   - Serve audit log delle modifiche configurazione?

4. **Multi-tenant**:
   - Quando si prevede l'uso multi-tenant?
   - Quali sono i criteri di isolamento? (per brand, per corso, altro?)

---

## 📝 NOTE

- Mantenere coerenza con codice esistente
- Seguire pattern architetturali già stabiliti
- Documentare API e configurazioni
- Testare integrazioni con dati reali
- Considerare backward compatibility

---

## 🎉 STATO ATTUALE AGGIORNATO (Gennaio 2026)

### ✅ COMPLETATO
- **Scheduler sequenziale completo** (00:30):
  1. Magellano → recupera e salva
  2. Ulixe → sync lead non rifiutate
  3. Meta Marketing → ingestion dati
  4. Meta Conversion API → eventi stati aggiornati
- **Integrazione Meta Marketing completa**:
  - Modelli DB, Service API, Interfaccia configurazione
  - Sincronizzazione automatica integrata nello scheduler
- **Dashboard Analytics 360°**:
  - Vista correlazione marketing ↔ feedback
  - Metriche aggregate, filtri avanzati
- **Riorganizzazione architettura**:
  - Separazione frontend/backend (directory `frontend/`)
  - Riorganizzazione `services/` in 3 directory (api/, integrations/, sync/)
  - 4 job autonomi separati invece di funzioni in un file
  - SyncOrchestrator per gestione pipeline
  - Docker configurato per includere frontend nell'immagine
- **Correlazione automatica Lead ↔ Marketing**:
  - Service `LeadCorrelationService` implementato
  - Match automatico usando campi Facebook da Magellano
  - Integrato nel sync job Magellano
- **Vista dettaglio lead estesa**:
  - Pagina `/leads/{id}` con due livelli di analisi
  - Overview per `msg_id` e per campagne Meta
  - Metriche marketing e timeline

### ⚠️ DA FARE
- **Grafici analytics**: trend, distribuzione, heatmap
- **Export e report**: CSV/Excel, report periodici
- **Logica selezione lead Ulixe**: definire meglio quali lead richiamare
- **Update Magellano**: quando necessario, implementare update stati

### 📊 PROSSIMI PASSI
1. ✅ ~~Eseguire migration database: `alembic upgrade head`~~ (Completato)
2. ✅ ~~Riorganizzazione struttura progetto~~ (Completato)
3. Configurare account Meta in `/settings/meta-accounts`
4. Testare pipeline completa scheduler
5. Definire strategia correlazione lead ↔ marketing
6. Implementare vista dettaglio lead estesa
