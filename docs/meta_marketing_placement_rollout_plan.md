# Piano di rollout: breakdown piattaforma/posizionamento Meta + allineamento lead

Documento operativo per **riattivare** `publisher_platform` e `platform_position` negli insights Marketing (Graph API), **validare** carico e rate limit, **modellare** i dati senza doppi conteggi, e **collegare** metriche aggregate a feedback Magellano dove l’attribuzione è realisticamente possibile.

**Contesto codebase:** `backend/services/integrations/meta_marketing.py` (`MetaMarketingService.get_insights`), `backend/services/sync/meta_marketing_sync.py` (`run_manual_sync`, job `run`), modelli in `backend/models.py` (`MetaMarketingData`, `Lead`), UI marketing in `backend/services/api/ui/marketing.py` e template correlati.

---

## 1. Obiettivi business e tecnici

### 1.1 Obiettivi doppi (entrambi validi)

| Obiettivo | Cosa serve in pratica | Fonte dati primaria |
|-----------|------------------------|---------------------|
| **Capire come “spende” l’algoritmo** | Dashboard con spend, impression, lead/conversioni **per piattaforma** (Facebook, Instagram, …) e **per posizionamento** (feed, stories, reels, …) dove Meta espone il breakdown. | Insights Marketing con `breakdowns` |
| **Capire quali feedback (Magellano) si associano a quali contesti di investimento** | Analisi **esito lead** (stato, categoria, ecc.) in relazione a **campagna ad / giorno** e, dove possibile, al **placement** come **indicatore aggregato** o proxy, non sempre attribuzione 1:1 per singola lead. | `Lead` + insights; eventuali lead Graph API |

### 1.2 Vincoli noti

- I **breakdown** moltiplicano il numero di righe restituite da Meta (stesso `ad_id`, stessa `date_start`, più combinazioni `publisher_platform` × `platform_position`).
- L’ingestion attuale assume **una riga salvata per `(ad_id, date)`** (lookup DB su `MetaMarketingData.ad_id` + `date`). Con i breakdown questo **non è più sufficiente** senza cambiare chiave logica o separare i layer (vedi sezione 4).
- Il campo **piattaforma** nell’export Magellano esiste ma la priorità è usare **dati dalla fonte Meta** per coerenza con spend e reporting.
- **Rate limit:** quota aumentata da Meta e chiamate già instrumentate (`_apply_dynamic_rate_limit`); va comunque **misurato** prima del cron in produzione.

---

## 2. Stato attuale nel codice (baseline)

### 2.1 `get_insights`

- **Non** passa `breakdowns` nella query Graph (`params` verso `.../insights`).
- I `fields` includono metriche standard; `publisher_platform` / `platform_position` **non** compaiono come chiavi nel dizionario normalizzato restituito (restano in `raw_data` se presenti nella risposta grezza).
- Commenti espliciti: breakdown esclusi per ridurre carico e rate limit.

### 2.2 `run_manual_sync` / job automatico

- Upsert concettuale su **(ad_id interno, data)**.
- `publisher_platform` **non** viene aggiornato in insert/update (commento “ridurre complessità ingestion”).
- `placement_info` è preparato ma **vuoto** in quel flusso.

### 2.3 Modello `MetaMarketingData`

- Colonne `publisher_platform` e `platform_position` **esistono già** (migration `029` nel repo).
- **Non** c’è una unique constraint su `(ad_id, date, publisher_platform, platform_position)` nella definizione modello letta; se si salvano più righe breakdown nella stessa tabella **senza** chiave composta, serve migration + indice univoco per evitare duplicati e race.

### 2.4 `Lead`

- `facebook_id`, `facebook_piattaforma`, `platform` (normalizzato), `meta_campaign_id`, `meta_adset_id`, `meta_ad_id`, stati Magellano (`magellano_status`, …), `magellano_subscr_date`.
- **Nessun** campo `platform_position` sul lead: il posizionamento “per lead” **non** è oggi modellato in DB; va introdotto solo se una fonte (Meta Graph / export) lo fornisce in modo affidabile.

---

## 3. Comportamento Meta Marketing API (Graph Insights)

### 3.1 Breakdown vs fields

- `publisher_platform` e `platform_position` si ottengono tramite parametro **`breakdowns`** (non come semplici `fields` aggiuntivi).
- Valori tipici `publisher_platform`: `facebook`, `instagram`, `audience_network`, `messenger`, … (documentazione Meta ufficiale).
- `platform_position` descrive il formato (es. feed, story, reels, search) dove disponibile per la combinazione.

### 3.2 Effetti sul volume di dati

- **Senza breakdown:** ~1 riga per `(ad, giorno)` a livello `ad`.
- **Con breakdown:** N righe per `(ad, giorno)` con N = numero di combinazioni con traffico.
- Impatto su: **tempo di risposta**, **pagine paginazione**, **chiamate successive**, **memoria** lato script.

### 3.3 Coerenza numerica (sanity check obbligatorio)

Per ogni `(ad_id, date)`:

- **Somma** di `spend` (e, se applicabile, `impressions`, `clicks`, conversioni da `actions`) sulle righe **con breakdown** dovrebbe essere **coerente** con una chiamata **senza** breakdown per lo stesso ad/giorno (tolleranza arrotondamenti Meta).

Questo check va implementato in **script di prova** e, se possibile, in **log di warning** durante sync in fase di rollout.

### 3.4 Parametri da fissare in implementazione

- `level`: restare su `ad` per allineamento a creatività/ad già sincronizzati.
- `time_increment`: `1` (daily) come oggi.
- `breakdowns`: elenco stringhe Meta (es. `publisher_platform`, `platform_position` — verificare compatibilità combinata nella versione Graph usata, es. `v23.0`).

---

## 4. Modello dati: raccomandazione (due layer)

### 4.1 Problema

Una sola tabella `MetaMarketingData` con **solo** righe breakdown **sostituisce** il totale giornaliero per ad; le query che oggi aggregano “una riga al giorno” **dovrebbero** sommare sulle righe breakdown o usare una riga “totale”.

Una sola tabella con **solo** righe totali **non** contiene il dettaglio placement.

### 4.2 Raccomandazione: **due layer espliciti**

| Layer | Contenuto | Chiave logica | Uso |
|-------|-----------|---------------|-----|
| **A – Totale giornaliero per ad** | Metriche aggregate **senza** breakdown (come oggi). | `(ad_id, date)` con `publisher_platform`/`platform_position` **NULL** (o flag `is_breakdown = false`) | KPI globali, confronti storici, job notturni leggeri, prediction che assumono una riga/ad/giorno |
| **B – Breakdown placement** | Stesse metriche (o subset) **per** `publisher_platform` + `platform_position`. | `(ad_id, date, publisher_platform, platform_position)` — con NULL gestiti esplicitamente | Marketing Analysis per placement, heatmap spend, CPL per placement |

**Implementazione possibile (scegliere una variante in fase di sviluppo):**

1. **Stessa tabella `MetaMarketingData`**  
   - Aggiungere colonna boolean **`is_placement_breakdown`** (default `false`) **oppure** convenzione: breakdown solo se `publisher_platform IS NOT NULL`.  
   - Unique constraint: `(ad_id, date, publisher_platform, platform_position)` — richiede **sentinella** per il totale (es. `publisher_platform` NULL univoco per riga totale).  
   - **Pro:** meno tabelle. **Contro:** query più complesse; rischio di errori se qualcuno filtra `WHERE publisher_platform IS NULL` pensando “dati mancanti” invece di “totale”.

2. **Tabella dedicata** `meta_marketing_placement` (nome indicativo)  
   - Colonne: FK a `meta_ads.id`, `date`, `publisher_platform`, `platform_position`, metriche numeriche, `additional_metrics` JSON, timestamp.  
   - Unique: `(ad_id, date, publisher_platform, platform_position)`.  
   - **`MetaMarketingData`** resta **solo** layer A (totale).  
   - **Pro:** separazione netta, query più chiare, meno regressioni sulle API esistenti. **Contro:** una migration in più e join quando servono entrambi.

**Raccomandazione finale:** **variante 2 (tabella dedicata)** se il team vuole minimizzare il rischio di **doppi conteggi** nelle query esistenti; **variante 1** se si preferisce meno join e si accetta disciplina rigorosa sui filtri SQL.

### 4.3 Collegamento `Lead` ↔ layer A/B

- **Forte:** `Lead.meta_ad_id` + data (es. `magellano_subscr_date` o data evento lead Meta) ↔ righe **per ad** (layer A o somma layer B).
- **Debole / proxy:** “placement” per singola lead confrontando **distribuzione** spend/lead su layer B nello stesso ad/giorno con **conteggi** lead Magellano per quell’ad/giorno — utile per **analisi aggregate**, non per affermare “questa lead era nello story” senza campo lead-level.

---

## 5. Piano di integrazione nel codice (sequenza suggerita)

### Fase 0 – Design freeze

- **Decisione (implementato):** variante **4.2.2** — tabella dedicata `meta_marketing_placement` (`MetaMarketingPlacement`); breakdown **sempre attivo** (nessun flag).
- **Lead Lead Ads (separato):** `GET /{ad_id}/leads` → tabella `meta_graph_leads` (`MetaGraphLead`), stesso range date di `run_manual_sync`, vedi `services/sync/meta_leads_graph_sync.py` e `MetaMarketingService.get_leads_for_ad`.
- Allineare la **versione Graph** (`v23.0` o successiva) con i limiti documentati per `breakdowns` multipli.

### Fase 1 – `MetaMarketingService`

- `get_insights`: parametro `breakdowns` opzionale; la sync manuale marketing passa **sempre** `publisher_platform` + `platform_position`.
- `get_leads_for_ad`: `GET /{ad_id}/leads` (paginato), usato solo dal flusso `meta_leads_graph_sync`.

### Fase 2 – Scrittura DB (marketing)

- **Una sola chiamata** `get_insights` **sempre** con breakdown (`publisher_platform`, `platform_position`).
- **Layer A (totali):** merge per `(ad_id, date)` → `meta_marketing_data`.
- **Layer B (dettaglio):** righe grezze → `meta_marketing_placement`.

### Fase 2b – Lead Lead Ads (separato, attivo con la sync manuale)

- Dopo il salvataggio marketing/placement, `sync_meta_graph_leads_for_account` interroga `get_leads_for_ad` per ogni ad dell’account e persiste in `meta_graph_leads` le lead con `created_time` (data **Europe/Rome**) nel range della sync.

### Fase 3 – API / UI

- **Marketing Analysis** (`/marketing/analysis`, sezioni placement): leggere da **layer B** (filtri `publisher_platform`, `platform_position` già presenti in parte nel codice UI).
- Verificare che KPI “globali” continuino a usare **layer A** o **somma controllata** di B.

### Fase 4 – Lead e Magellano

- Nessun cambiamento obbligatorio per **solo** dashboard spend; per “feedback per placement”:
  - **Opzione A:** report che unisce `Lead` filtrato per `meta_ad_id` + date con **aggregati** layer B (stesso ad, stessa data).
  - **Opzione B (futuro):** se Graph espone placement su oggetto Lead, migration per `Lead.platform_position` e popolamento da sync — **solo dopo** verifica campi API.

---

## 6. Script locale e stress test (incrementale)

### 6.1 Script locale “1:1”

**Obiettivo:** replicare **stesso** token, account, range date e parametri del servizio, ma con **logging esteso** e **nessun write** (o write su DB di sviluppo).

Contenuto minimo:

1. Caricare token/account come fa `run_manual_sync` (stesso decrypt).
2. Chiamare `get_insights` **senza** breakdown → contare righe, loggare sample.
3. Chiamare `get_insights` **con** breakdown → contare righe, loggare sample.
4. Per un sottoinsieme di `(ad_id, date)`, eseguire **check somma** spend (e altre metriche) B vs A.
5. Scrivere output su file (opzionale) con timestamp nel nome file per backup/audit.

**Percorso suggerito:** `backend/scripts/` con prefisso chiaro, es. `test_meta_insights_placement_breakdown.py` (nome definitivo a convenzione repo).

### 6.2 Matrice stress test (account singolo)

| Step | Account | Finestra | Breakdown | Obiettivo misura |
|------|---------|----------|-----------|------------------|
| 1 | 1 scelto | **1 giorno** | sì | Baseline tempo, righe, errori rate limit |
| 2 | stesso | **3 giorni** | sì | Scalabilità lineare |
| 3 | stesso | **5 giorni** | sì | |
| 4 | stesso | **7 giorni** | sì | Vicino a uso settimanale |
| 5 | stesso | **15 giorni** | sì | Stress retroattivo |

**Metriche da registrare per ogni step:**

- Durata totale e tempo per pagina.
- `len(insights)` (o righe totali).
- Eventuali HTTP `429`, `4xx`, `5xx`.
- Esito **sanity check** somme (vedi 3.3).
- Uso memoria se script in locale.

### 6.3 Criteri di “go” per produzione

- Nessun errore sistematico di quota per lo step **15 giorni** sull’account pilota.
- Sanity check entro soglia accettata (definire es. ±0,5% o policy interna).
- **Stima** durata job notturno per tutti gli account (moltiplicare per N account se sync seriale).

---

## 7. Allineamento lead Meta ↔ Magellano (fase di analisi)

### 7.1 Dati disponibili

- **Magellano:** `magellano_id`, `facebook_id`, stati, `meta_ad_id`, date.
- **Meta (insights):** spend/lead per placement **aggregati**.
- **Meta (lead):** da definire quale endpoint e quali campi (ad_id, created_time, form_id, …); placement **non** garantito.

### 7.2 Analisi “come sono andati i posizionamenti”

Interpretazione realistica:

- **Livello 1:** KPI placement da insights (spend, CPL proxy da conversioni Meta) — **sempre** possibile con breakdown.
- **Livello 2:** **Stesso ad**, stesso giorno: confronto **numero lead Magellano** vs **distribuzione** metriche su placement — **analisi composita**, non per-lead.
- **Livello 3:** attribution per-lead a placement solo se **campo** presente sul payload lead Graph — **da validare** prima di implementare colonne su `Lead`.

---

## 8. Rischi e mitigazioni

| Rischio | Mitigazione |
|---------|-------------|
| Rate limit superato | Sync breakdown **meno frequente** del totale (es. giornaliero totale + breakdown 1x/settimana); backoff esistente; finestre incrementali. |
| Doppi conteggi in UI | Layer A + B separati o flag/univoco chiaro; query review; test su dashboard. |
| Incoerenza Meta somme | Check automatico 3.3 in script e log. |
| Scope creep prediction | Documentare `meta_marketing_placement_rollout_plan.md` in `marketing_prediction_implementation.md` se le feature di breakdown entrano nel feature store. |

---

## 9. Checklist implementazione (ordine operativo)

- [x] Decisione **variante 4.2.2** — migration `030_meta_marketing_placement_table`, modello `MetaMarketingPlacement`.
- [x] Estendere `get_insights` con `breakdowns` opzionale e parsing `publisher_platform` / `platform_position`.
- [x] Una chiamata Insights con breakdown; merge → `meta_marketing_data`, righe grezze → `meta_marketing_placement` (`run_manual_sync`).
- [x] Script locale **6.1** — `backend/scripts/test_meta_insights_placement_breakdown.py` (matrice **6.2** manuale).
- [x] Aggiornare query **Marketing Analysis** e API marketing per leggere layer B dove serve.
- [ ] Documentare in README interno o in questo file i **tempi** e i **limiti** osservati post stress test.
- [ ] (Opzionale) Explorazione lead Graph per **placement** su oggetto lead prima di nuove colonne `Lead`.

---

## 10. Riferimenti file nel repository

| Area | File |
|------|------|
| Insights API | `backend/services/integrations/meta_marketing.py` |
| Sync marketing | `backend/services/sync/meta_marketing_sync.py` |
| Modelli | `backend/models.py` (`MetaMarketingData`, `MetaMarketingPlacement`, `Lead`, `MetaAd`, …) |
| UI marketing | `backend/services/api/ui/marketing.py`, `frontend/templates/marketing_analysis.html` |
| Predizione (impatto futuro) | `docs/marketing_prediction_implementation.md` |

---

*Documento generato per il rollout breakdown placement Meta; aggiornare le sezioni “decisione” e “metriche osservate” dopo lo stress test.*
