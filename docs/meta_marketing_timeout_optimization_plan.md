# Piano operativo dettagliato - Ottimizzazione timeout Meta Marketing (A-B-C)

## Obiettivo

Ridurre timeout e saturazione quota nella sync Meta Marketing intervenendo su:

- **A**: singola estrazione `insights` per account/range a `level=ad`
- **B**: ricostruzione/aggregazione di `adset` e `campaign` partendo dai dati ad-level
- **C**: throttling automatico "quota-aware" + alert email su soglie critiche

## Scope (in/out)

### In scope

- Refactor della sync manuale/cron per evitare chiamate duplicate a `get_insights`
- Standardizzazione campi richiesti per `level=ad` (`ad_id`, `adset_id`, `campaign_id`, `date_start`)
- Aggregazioni interne da ad-level verso adset/campaign
- Lettura header usage quota e applicazione sleep/backoff dinamico
- Integrazione alert su soglia quota critica con infrastruttura alert esistente

### Out of scope (esplicitamente escluso in questa fase)

- Async Reports (`AdReportRun`) -> fase successiva
- Batch API da 50 chiamate -> non implementata in questa fase
- Refactor completo pipeline campagne/adset/ads oltre il minimo necessario

---

## Stato attuale e problemi concreti

1. In `run_manual_sync`, `get_insights(...)` viene richiamata dentro il loop campagne.
2. La chiamata e account-level (non filtrata per singola campagna), quindi viene ripetuta inutilmente N volte.
3. Il retry attuale gestisce timeout/rate limit ma con backoff statico e senza adattamento alla quota reale.
4. Non c'e una politica centralizzata che legga gli header quota per modulare il ritmo.

Conseguenza: chiamate duplicate, runtime elevato, timeout frequenti, quota consumata rapidamente.

---

## Strategia implementativa

## Fase 1 - A: singola chiamata insights ad-level per account/range

### Obiettivo

Fare **una sola chiamata** `get_insights(level='ad')` per account e periodo, fuori dal loop campagne.

### Modifiche previste

### File: `backend/services/sync/meta_marketing_sync.py`

- Spostare `service.get_insights(...)` prima del loop campagne.
- Costruire struttura in memoria indicizzata per:
  - `campaign_id -> [insights]`
  - `ad_id -> [insights]` (utile per matching DB)
- Nel loop campagne usare solo i dati gia estratti e filtrati.

### Regole dati

- Campi minimi obbligatori richiesti a Meta:
  - `date_start`
  - `ad_id`
  - `adset_id`
  - `campaign_id`
  - metriche selezionate
- Se uno dei campi ID manca: record scartato con conteggio tecnico di scarto.

### Deliverable

- `run_manual_sync` con una sola estrazione insights per account/range.
- Statistiche run aggiornate:
  - `insights_total_rows`
  - `insights_rows_with_missing_ids`
  - `insights_rows_matched_to_ads`

---

## Fase 2 - B: aggregazioni da ad-level verso adset/campaign

### Obiettivo

Confermare che i dati ad-level sono sufficienti e calcolare aggregazioni coerenti senza chiamate aggiuntive.

### Modifiche previste

### File: `backend/services/sync/meta_marketing_sync.py`

- Introdurre helper interni:
  - `_group_insights_by_campaign(...)`
  - `_group_insights_by_adset(...)`
  - `_safe_sum_numeric_metrics(...)`
- Utilizzare `campaign_id` e `adset_id` presenti in ogni riga ad-level per aggregare:
  - `spend`
  - `impressions`
  - `clicks`
  - `conversions`
- Calcolare metriche derivate aggregate:
  - `ctr = clicks / impressions * 100`
  - `cpc = spend / clicks`
  - `cpm = spend / impressions * 1000`

### Nota architetturale

Per lo storage attuale su `MetaMarketingData` (ad-level) non e necessario salvare subito nuove tabelle aggregate: le aggregazioni possono essere:

- on-demand lato servizio per controllo qualità e reporting tecnico
- riusate in step successivi per endpoint/report futuri

### Deliverable

- Funzioni aggregate testabili e deterministiche
- Coerenza numerica verificata:
  - somma ad-level == valore aggregato adset/campaign (a parita di perimetro)

---

## Fase 3 - C: throttling automatico con usage headers + alert

### Obiettivo

Passare da delay statico a gestione dinamica basata su quota effettiva.

### Modifiche previste

### File: `backend/services/integrations/meta_marketing.py`

- Introdurre un wrapper centralizzato per chiamate Meta che:
  1. esegue request
  2. estrae header quota (quando disponibili)
  3. calcola livello pressione quota
  4. decide sleep/backoff dinamico

- Nuovi helper:
  - `_extract_usage_headers(...)`
  - `_parse_usage_percent(...)`
  - `_compute_dynamic_delay(...)`
  - `_should_trigger_quota_alert(...)`

### Policy suggerita (prima versione)

- **quota < 80%**: delay base
- **80% <= quota < 90%**: delay medio (x1.5 / x2)
- **90% <= quota < 95%**: delay alto + warning tecnico
- **quota >= 95%**: pausa lunga + retry controllato
- **quota >= 98% ripetuta**: interrompere il job con errore esplicito e alert email

### Alert email

Usare `send_sync_alert_if_needed(...)` con `sync_type` coerente (`meta_marketing_sync`) e payload tecnico:

- account_id
- periodo richiesto
- valore quota letto
- numero eventi critici consecutivi
- azione presa (sleep/stop)

### File coinvolti

- `backend/services/integrations/meta_marketing.py` (core throttling)
- `backend/services/sync/meta_marketing_sync.py` (propagazione contesto account/job)
- eventuale riuso `backend/services/utils/alert_sender.py` (gia presente)

---

## Piano tecnico file-by-file

## 1) `backend/services/sync/meta_marketing_sync.py`

- Refactor `run_manual_sync`:
  - fetch insights una volta per account/range
  - indexing in memoria per `campaign_id` e `ad_id`
  - loop campagne senza nuova chiamata a Meta
- Aggiornamento contatori statistici
- Gestione robusta campi mancanti (`""` dove sensato, mai valori fittizi fuorvianti)

## 2) `backend/services/integrations/meta_marketing.py`

- Estensione `_make_api_call_with_retry` con logica quota-aware
- Parsing safe di header JSON/stringa
- Delay dinamico prima della chiamata successiva
- Escalation automatica su soglie critiche

## 3) `backend/tasks/meta_marketing.py` (solo se necessario)

- Assicurare che eventuale errore quota critica sia classificato in modo leggibile nel `job.message`
- Non cambiare semantica task oltre la reportistica essenziale

---

## Test plan dettagliato

## Test unitari (nuovi)

- Parsing header:
  - header assenti
  - header malformati
  - header JSON validi
- `compute_dynamic_delay`:
  - soglie 79/80/89/90/95/98
- Aggregazioni:
  - dataset sintetico con 2 campaign, 3 adset, N ad
  - verifica somme e metriche derivate

## Test integrazione (locale/staging)

1. Sync manuale 1 account, 1 giorno
   - nessun timeout
   - numero chiamate insights ridotto (una per account/range)
2. Sync manuale 1 account, 7 giorni
   - runtime inferiore rispetto baseline
   - nessuna duplicazione record
3. Simulazione quota alta (mock parser/policy)
   - sleep dinamico applicato
   - trigger alert su soglia critica

## Test regressione

- Confronto prima/dopo su:
  - `campaigns_synced`
  - `records_created/updated`
  - qualità matching ad_id

---

## KPI di successo (misurabili)

- Riduzione chiamate insights per account: **da N campagne a 1**
- Riduzione timeout sync manuale su range breve: target **-60% / -80%**
- Riduzione errori rate-limit/timeout totali per job
- Nessuna regressione su numero record marketing scritti

---

## Rollout e fallback

## Rollout consigliato

1. Deploy con feature attiva su un solo account pilota
2. Verifica 2-3 run giornalieri
3. Estensione a tutti gli account attivi

## Fallback rapido

Se emergono anomalie:

- disattivare policy dinamica mantenendo retry esistente
- mantenere comunque il refactor A (single-fetch insights), che resta il guadagno principale

---

## Rischi e mitigazioni

- **Rischio parsing header non uniforme**  
  Mitigazione: parser permissivo + default safe (delay base)

- **Rischio stop eccessivo per soglie aggressive**  
  Mitigazione: soglie configurabili e tuning graduale

- **Rischio mismatch aggregazioni**  
  Mitigazione: test coerenza somme e confronti run baseline

---

## Checklist esecutiva

- [ ] Refactor `run_manual_sync` con single-fetch insights account/range
- [ ] Indexing insights by `campaign_id`/`ad_id`
- [ ] Helper aggregazione adset/campaign da ad-level
- [ ] Parser header usage robusto
- [ ] Policy delay dinamico + escalation
- [ ] Trigger alert email su quota critica
- [ ] Test unitari parser/policy/aggregazioni
- [ ] Test integrazione su account pilota
- [ ] Rollout progressivo

---

## Roadmap successiva (non in questa delivery)

- Async Reports per range lunghi/backfill
- Batch API da 50 chiamate solo per endpoint adatti (non per sostituire indiscriminatamente insights)

