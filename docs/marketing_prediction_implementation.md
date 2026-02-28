# Implementazione modulo Marketing Prediction

Documento tecnico per l’implementazione del modulo di **predizione performance ADV** (lead gen, CPL, early warning) nell’applicazione cepu-lavorazioni.  
Il contesto business e le scelte strategiche sono in [prediction.md](./prediction.md).

---

## 1. Obiettivi e requisiti

### 1.1 Obiettivi business

- Prevedere **volume di lead** e **CPL atteso** per campagna / adset / creatività in un orizzonte temporale configurabile.
- Identificare **campagne/creatività ad alto rischio** (underperformance, CPL in salita) per intervento anticipato.
- Supporto **decisionale** (no automazione budget): l’utente vede previsioni e alert e decide.

### 1.2 Requisiti funzionali (da rispettare in fase di implementazione)

| Requisito | Descrizione |
|-----------|-------------|
| **KPI dinamici** | I KPI da prevedere (es. lead, CPL, P(sforamento)) sono **impostabili da front-end** (select/checkbox), non fissi in backend. |
| **Vista totale + drill-down** | Vista aggregata (es. per account) con drill-down su campagna → adset → creatività. Utile sia “quale campagna va bene” sia “quale creatività va male”. |
| **Orizzonte multiplo** | Previsioni per **7, 14, 30 giorni**: da più “chiare” (7d) a più “trend” (30d). |
| **Outcome di riferimento** | Per ora solo **stato Magellano** (lead gen form nativo Meta); non si ragiona su chiusure/Ulixe in questa prima fase. |
| **Stack** | Backend **Python** (FastAPI esistente), modelli tabular (LightGBM/CatBoost), batch scoring giornaliero. |

### 1.3 Riferimenti nel codebase

- Route pagina: `GET /marketing/prediction` → `marketing_prediction()` in `backend/services/api/ui/marketing.py`.
- Template: `frontend/templates/marketing_prediction.html` (attualmente placeholder WIP).
- Dati: `MetaMarketingData`, `MetaAd`, `MetaAdSet`, `MetaCampaign`, `MetaAccount`, `Lead` (correlazione e stato Magellano) in `backend/models.py`.

---

## 2. Architettura del modulo

### 2.1 Componenti

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Frontend (marketing_prediction.html + JS)                               │
│  - Filtri: account, campagna, adset, date range                          │
│  - Select KPI (lead, CPL, P(sforamento), …) + orizzonte (7/14/30 gg)     │
│  - Tabella/grafici: totale → drill-down campagna → adset → creative      │
└─────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  API (backend/services/api/ui/marketing.py + eventuale sotto-modulo)    │
│  - GET /api/marketing/predictions?metric=...&horizon=...&...             │
│  - GET /api/marketing/prediction-config (lista KPI e orizzonti)          │
└─────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Servizio di scoring (backend/services/prediction/ o scripts/)           │
│  - Lettura feature da tabella gold / vista materializzata               │
│  - Caricamento modello (per metrica + orizzonte)                         │
│  - Restituzione previsioni aggregate e per entità (account/campagna/…)    │
└─────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Storage previsioni (opzionale ma consigliato)                           │
│  - Tabella predictions_adset_day (o simile) aggiornata da job batch     │
│  - Consente dashboard veloci e storico per backtest/report               │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Pipeline offline (training + backtest)

- **Feature engineering**: script che popola una tabella/vista “gold” (es. `adset_day_features`) **senza data leakage** (solo dati fino a `t`).
- **Training**: job (cron o Prefect) che addestra modelli per (metrica, orizzonte), con split temporale e salvataggio modello + metriche.
- **Backtest**: walk-forward su storico; metriche (MAE, RMSE, PR-AUC, ecc.) per orizzonte e per segmento.
- **Batch scoring**: job giornaliero che calcola feature aggiornate, esegue scoring e scrive in `predictions_*` per uso API/dashboard.

---

## 3. Modello dati e dataset

### 3.1 Entità esistenti (da usare)

- **MetaAccount**, **MetaCampaign**, **MetaAdSet**, **MetaAd**: gerarchia ADV.
- **MetaMarketingData**: una riga per (ad_id, date) con spend, impressions, clicks, conversions, ctr, cpc, cpm, cpa.
- **Lead**: magellano_id, meta_campaign_id, meta_adset_id, meta_ad_id, magellano_status, magellano_status_category, magellano_subscr_date; correlazione con ADV per “lead per ad/adset/campagna”.

Per la **predizione** si lavora a livello **adset-day** (e opzionale **creative-day**): una riga per (adset_id, date) con feature e target.

### 3.2 Tabella/vista “gold” (feature store)

Unità: **adset-day** (e eventuale creative-day).

**Colonne suggerite per `adset_day_features`:**

| Gruppo | Nome colonna | Descrizione | Note anti-leakage |
|--------|--------------|-------------|-------------------|
| Chiave | adset_id, date | Identificativo e data di riferimento | date = giorno a cui si riferiscono le feature (tutto calcolato fino a date incluso) |
| Target (per training) | lead_count_7d, lead_count_14d, lead_count_30d | Lead (Magellano) nei prossimi 7/14/30 giorni | Calcolati solo in training; in serving non presenti |
| Target | cpl_7d, cpl_14d, cpl_30d | CPL medio nei prossimi 7/14/30 giorni | Idem |
| Lag / rolling | spend_1d, spend_3d, spend_7d, spend_14d | Spesa ultimi 1/3/7/14 giorni | Solo fino a `date` |
| | ctr_7d_avg, cpc_7d_avg, cpm_7d_avg | Medie ultimi 7 giorni | Solo fino a `date` |
| | conversions_7d, conversions_14d | Conversioni (Meta) ultimi 7/14 giorni | Solo fino a `date` |
| | cpl_7d_hist, cpl_14d_hist | CPL storico ultimi 7/14 giorni | Solo fino a `date` |
| Contesto | day_of_week, month, is_month_start, is_month_end | Calendario | Per stagionalità |
| Contesto | campaign_id, account_id | Per aggregazioni e filtri | |
| Contesto | days_active, days_since_first | Giorni attivi dell’adset, giorni dalla prima data | Solo fino a `date` |

Le **conversioni/lead** usate come target devono essere quelle **Magellano** (conteggio da `Lead` filtrato per stato/account/campagna) se disponibili e allineate; altrimenti si usa `MetaMarketingData.conversions` come proxy, documentando la scelta.

### 3.3 Tabelle previsioni (output del batch scoring)

Esempio **predictions_adset_day**:

- `adset_id`, `account_id`, `campaign_id` (opzionale creative_id se si aggiunge creative-day).
- `reference_date`: data in cui è stata calcolata la previsione.
- `horizon_days`: 7, 14, 30.
- `metric`: es. `lead_count`, `cpl`, `p_cpl_above_threshold`.
- `value`: valore previsto (numero o probabilità).
- `threshold` (opzionale): soglia usata per P(sforamento), se applicabile.

L’API può leggere da qui (filtrando per reference_date = “ultimo run”) oppure ricalcolare on-the-fly se il volume è modesto.

---

## 4. Feature engineering (dettaglio e anti-leakage)

### 4.1 Regola fondamentale

Per ogni riga con `date = T`:
- **Feature**: solo dati disponibili **fino a T** (incluso).
- **Target**: solo eventi nei giorni **dopo T** (T+1 … T+7, T+1 … T+14, T+1 … T+30).

Esempio: per `date = 2025-01-15`, `spend_7d` = spesa dal 09 al 15 gennaio; `lead_count_7d` = lead con magellano_subscr_date (o created_at) tra 16 e 22 gennaio.

### 4.2 Lead “Magellano”

- Fonte: tabella `Lead`.
- Filtro: es. `magellano_status_category == 'CRM'` o altro stato considerato “lead valido” (da definire in config).
- Attribuzione: per `meta_adset_id` (e opzionale meta_ad_id) e intervallo date di iscrizione.
- Se non si è pronti per il join Lead↔AdSet, usare `MetaMarketingData.conversions` come proxy e documentarlo.

### 4.3 Implementazione suggerita

- Script (es. `backend/scripts/features/build_adset_day_features.py`) che:
  - Legge da DB (MetaMarketingData + Lead se usato) e costruisce DataFrame con righe (adset_id, date).
  - Calcola rolling/lag con `pandas` (es. `groupby(adset_id).rolling(7).sum()` su date ordinata).
  - Calcola target per finestre future (shift negativo o merge su date).
  - Salva in tabella `adset_day_features` o in Parquet per training.

---

## 5. Modelli e training

### 5.1 Scelta algoritmo

- **Regressione** (lead attesi, CPL atteso): **LightGBM** o **CatBoost**.
  - LightGBM: veloce, buon supporto categoriche con encoding.
  - CatBoost: comodo se ci sono molti ID (campaign_id, adset_id, account_id) senza preprocessing.
- **Classificazione** (es. P(CPL > soglia)): stesso algoritmo, modalità binaria; soglia configurabile (parametro da front-end o config).

Un modello per (metrica, orizzonte), es.:
- (lead_count, 7), (lead_count, 14), (lead_count, 30),
- (cpl, 7), (cpl, 14), (cpl, 30),
- (p_cpl_above_threshold, 7), (p_cpl_above_threshold, 14), (p_cpl_above_threshold, 30) — con soglia passata a training o fissata.

### 5.2 Split temporale (no random)

- **Train**: es. da `min_date` a `train_end` (es. -60 giorni da fine storico).
- **Validation**: da `train_end + 1` a `val_end` (es. -30 giorni).
- **Test**: da `val_end + 1` a fine dati (toccato solo per report finale).

Per **backtest walk-forward**: finestra mobile (es. train = ultimi 90 giorni), step = 7 giorni; per ogni step si addestra e si valida sul periodo successivo (7/14/30 giorni), poi si avanza.

### 5.3 Metriche

- **Regressione**: MAE, RMSE; errore medio quando “predicted CPL > soglia” vs “actual CPL > soglia”.
- **Classificazione**: PR-AUC, precision/recall a soglia fissata, calibration (probabilità vs frequenza osservata).
- Salvare per (run_id, metric, horizon_days, segment) in `model_metrics_backtest` o in report (es. CSV/MLflow).

### 5.4 Interpretabilità

- **SHAP**: valori per ogni feature per ogni predizione (o campione); in API restituire “top 3 driver” per riga (es. “CVR↓, CPC↑, frequency↑”) per rendere la previsione azionabile.

### 5.5 Registro modelli

- Salvare per ogni (metric, horizon): `model.pkl` (o formato nativo LightGBM/CatBoost), `config.yaml` (iperparametri, soglia, date training), `metrics.json`.
- Opzionale: MLflow per run, metriche e artifact.

---

## 6. Backtesting

### 6.1 Strategia

- **Walk-forward**: per ogni data di riferimento `T` (es. ogni settimana):
  - Train su [T - 90, T] (o 180 giorni).
  - Prevedi per T+1…T+7, T+1…T+14, T+1…T+30.
  - Confronta con valori reali quando disponibili.
- **Aggregazione**: per orizzonte e (opzionale) per segmento (account, campagna, adset) per vedere dove il modello è più stabile.

### 6.2 Output

- Metriche (MAE, RMSE, PR-AUC, …) per orizzonte e periodo.
- Report (CSV o tabella) che possa essere esposto in una sezione “Storico backtest” in UI o in docs.

### 6.3 Cosa evitare

- Random split train/test.
- Feature che usano informazioni “future” (es. CPL medio che include il giorno target).
- Riutilizzare il test set per scelte di modello/feature (solo per stima finale).

---

## 7. API

### 7.1 Endpoint previsioni

**GET** `/api/marketing/predictions`

Parametri query (tutti coerenti con i requisiti):

| Parametro | Tipo | Descrizione |
|-----------|------|-------------|
| metric | string | KPI da prevedere: `lead_count`, `cpl`, `p_cpl_above_threshold`, … (valori da config). |
| horizon_days | int | 7, 14, 30. |
| account_id | string | opzionale; filtra per account. |
| campaign_id | string | opzionale; filtra per campagna. |
| adset_id | int | opzionale; filtra per adset. |
| reference_date | date | opzionale; default = ultima data per cui esistono previsioni. |
| threshold | float | opzionale; per metric = `p_cpl_above_threshold`, soglia CPL. |
| level | string | opzionale; `account`, `campaign`, `adset`, `creative`; default = adset. |

Risposta (esempio):

```json
{
  "reference_date": "2025-02-27",
  "metric": "cpl",
  "horizon_days": 7,
  "threshold": null,
  "data": [
    {
      "account_id": "123",
      "account_name": "...",
      "campaign_id": "456",
      "campaign_name": "...",
      "adset_id": 789,
      "adset_name": "...",
      "value": 12.5,
      "top_drivers": ["cpl_7d_hist ↑", "ctr_7d_avg ↓", "spend_7d ↑"]
    }
  ],
  "aggregate": {
    "total_predicted_leads": 1200,
    "weighted_avg_cpl": 11.2
  }
}
```

Per **drill-down**: stesso endpoint con `level=account` per totale, poi `level=campaign` con `account_id`, poi `level=adset` con `campaign_id`, ecc. Oppure un unico livello “adset” e aggregazione lato front-end.

### 7.2 Configurazione KPI e orizzonti

**GET** `/api/marketing/prediction-config`

Risposta (esempio):

```json
{
  "metrics": [
    { "id": "lead_count", "label": "Lead attesi", "type": "regression" },
    { "id": "cpl", "label": "CPL atteso", "type": "regression" },
    { "id": "p_cpl_above_threshold", "label": "Prob. CPL sopra soglia", "type": "classification", "requires_threshold": true }
  ],
  "horizons_days": [7, 14, 30],
  "default_metric": "lead_count",
  "default_horizon_days": 7
}
```

Il front-end usa questa lista per popolare i select e inviare le richieste con `metric` e `horizon_days` (e `threshold` se serve).

---

## 8. Front-end (pagina Prediction)

### 8.1 Layout

- **Filtri**: stessa logica di Marketing Analysis (account, campagna, adset, intervallo date); aggiungere:
  - **KPI**: select da `prediction-config` (metric).
  - **Orizzonte**: 7 / 14 / 30 giorni.
  - **Soglia** (se metric = P(CPL > soglia): input numerico.
- **Blocco principale**:
  - Vista **totale** (es. una card o riga con “Lead attesi (7 gg)”, “CPL medio atteso”, “N° adset a rischio”, ecc.).
  - **Tabella** con drill-down: prima righe per campagna (o account), espandibile per adset e per creatività; colonne: nome, valore previsto, eventuali “top drivers”, indicatore rischio/alert.
- **Grafici** (fase successiva): previsioni vs storico (linee), eventuali bande di confidenza se il modello le produce.

### 8.2 Comportamento

- Al cambio di filtri / KPI / orizzonte / soglia: chiamata a `GET /api/marketing/predictions` con i parametri aggiornati.
- Gestione stati: loading, errore, “dati insufficienti” (es. storico troppo corto per quell’adset).

---

## 9. Struttura file e cartelle (proposta)

```
backend/
  services/
    api/
      ui/
        marketing.py              # Estendere con route /api/marketing/predictions e prediction-config
    prediction/                   # Nuovo modulo (opzionale: può stare in scripts/)
      features.py                 # Costruzione feature (adset-day) senza leakage
      training.py                 # Split temporale, train, validation, salvataggio modello
      scoring.py                  # Caricamento modello, feature correnti, predict
      config.py                   # Metriche, orizzonti, soglie default
  scripts/
    prediction/
      build_features.py           # Job che popola adset_day_features
      train_models.py             # Job training (tutti le metriche/orizzonti o solo quelli aggiornati)
      run_backtest.py             # Walk-forward backtest, report metriche
      daily_scoring.py            # Score giornaliero e scrittura predictions_*
  models.py                       # Aggiungere eventuali tabelle: adset_day_features, predictions_adset_day, model_metrics_backtest
  alembic/
    versions/
      xxx_add_prediction_tables.py
frontend/
  templates/
    marketing_prediction.html     # Sostituire placeholder con filtri, tabella, (grafici)
  static/                         # JS per chiamate API e drill-down (se non già in template)
docs/
  prediction.md                   # Contesto business (esistente)
  marketing_prediction_implementation.md  # Questo documento
```

---

## 10. Job e orchestrazione

### 10.1 Job consigliati

| Job | Frequenza | Descrizione |
|-----|-----------|-------------|
| build_features | Giornaliero (dopo sync Meta) | Aggiorna `adset_day_features` fino a ieri. |
| train_models | Settimanale (o su richiesta) | Riprende dati gold, split temporale, addestra modelli per (metric, horizon), salva artifact e metriche. |
| run_backtest | Su richiesta / mensile | Walk-forward su storico, scrive report in `model_metrics_backtest` o file. |
| daily_scoring | Giornaliero | Legge feature aggiornate, carica modelli, scrive `predictions_adset_day` (o altro) per reference_date = oggi. |

### 10.2 Orchestrazione

- MVP: **cron** (es. 06:00 build_features, 07:00 daily_scoring).
- Evoluzione: **Prefect** o altro scheduler per dipendenze e retry.

---

## 11. Validazione e qualità

### 11.1 Controlli in training

- Verificare che nessuna feature usi dati oltre `date`.
- Verificare che i target usino solo finestre future (T+1 … T+k).
- Monitorare gap train vs validation (es. RMSE): se validation >> train, possibile overfitting o drift.

### 11.2 Controlli in produzione

- Confronto periodico “previsione vs realizzato” (es. dopo 7 giorni) e aggiornamento metriche in DB o report.
- Alert (opzionale) se metriche di backtest peggiorano oltre una soglia.

### 11.3 Limiti minimi

- Definire (es. in config): minimo giorni di storico per adset/campagna per mostrare previsione (es. almeno 7 giorni con dati); sotto soglia mostrare “dati insufficienti” in UI.

---

## 12. Fasi di implementazione suggerite

| Fase | Contenuto | Deliverable |
|------|------------|-------------|
| 1 | Modello dati: tabella gold `adset_day_features` + tabella `predictions_adset_day`; script feature engineering con regole anti-leakage | Migration, script build_features.py |
| 2 | Training: uno script che legge gold, fa split temporale, addestra un modello (es. CPL 7d) e salva modello + metriche | train_models.py, modello + config |
| 3 | Backtest: script walk-forward con metriche (MAE, RMSE) per orizzonte 7/14/30 | run_backtest.py, report |
| 4 | Scoring: script che legge feature, carica modello, scrive previsioni in DB | daily_scoring.py |
| 5 | API: GET predictions e prediction-config; integrazione con filtri e KPI/orizzonte dinamici | marketing.py + eventuale prediction/service |
| 6 | Front-end: aggiornamento marketing_prediction.html con filtri, select KPI/orizzonte, tabella e drill-down | Template + JS |
| 7 | Estensione: più metriche (lead, P(sforamento)), SHAP/top_drivers, grafici previsioni vs storico | Modelli aggiuntivi, API, UI |

---

## 13. Riferimenti incrociati

- **prediction.md**: obiettivi business, CPL target, margine, qualità lead, stagionalità education, stack Python, tabelle gold.
- **marketing.py**: route `/marketing/prediction`, `/marketing/analysis`, API campagne/adset/ads; riuso logica filtri e permessi (account per user).
- **models.py**: `MetaMarketingData`, `MetaAd`, `MetaAdSet`, `MetaCampaign`, `MetaAccount`, `Lead`, `StatusCategory` (Magellano).

---

*Ultimo aggiornamento: documento creato per implementazione modulo Marketing Prediction; da aggiornare al progresso delle fasi.*
