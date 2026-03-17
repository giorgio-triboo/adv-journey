## Filtri per piattaforma (Facebook / Instagram) e breakdown in Marketing

Documento tecnico per l’implementazione del filtro per piattaforma (FB/IG) e dei breakdown per piattaforma nelle viste Marketing (`/marketing` e `/marketing/analysis`).

---

## 1. Obiettivi e perimetro

### 1.1 Obiettivi

- **Filtri piattaforma in vista Marketing gerarchica** (`/marketing`):
  - Aggiungere un filtro che consenta di scegliere **Facebook**, **Instagram** o **entrambe**.
  - Tutti i KPI (Meta, Magellano, Ulixe) devono riflettere solo la piattaforma selezionata.
- **Breakdown per piattaforma in Marketing Analysis** (`/marketing/analysis`):
  - Nuova sezione sotto i KPI globali con **card e grafici separati** per Facebook e Instagram.
- **Preparazione dati**:
  - Tracciare in modo strutturato la **piattaforma** e, facoltativamente, la **position** (feed, stories, ecc.) nei dati Meta.
  - Tracciare la piattaforma anche sulle **Lead (Magellano)**, usando l’export unificato già disponibile.

### 1.2 Fuori scope

- Nessun cambiamento alla logica di **pay**, **ricavo**, **margine**: cambia solo il sottoinsieme di dati considerato.
- Nessuna modifica alla sincronizzazione Magellano/Ulixe oltre all’aggiunta del campo piattaforma sulle lead.
- Nessuna modifica ai modelli di prediction (vedi `marketing_prediction_implementation.md`).

---

## 2. Modifiche al modello dati

### 2.1 `MetaMarketingData`: piattaforma e position

**Obiettivo**: sapere per ogni riga di insight Meta **da quale piattaforma** proviene lo spend/conversion (FB, IG, ecc.) e, opzionalmente, la position (feed, stories, reels…).

**Azioni:**

1. **Nuova migration Alembic** (es. `0xx_add_platform_to_meta_marketing_data.py`):
   - Aggiungere a `MetaMarketingData`:
     - `publisher_platform`: `String`/`Enum`, nullable.
     - `platform_position`: `String`, nullable.
2. Aggiornare il modello SQLAlchemy in `models.py`:
   - Aggiungere i due campi con tipi coerenti alla migration.
3. Verificare che l’indice esistente su `(ad_id, date)` resti invariato; non sono richiesti nuovi indici inizialmente (eventuali indici su `publisher_platform` si possono aggiungere in un secondo momento se le query risultano lente).

### 2.2 `Lead`: piattaforma di provenienza

**Obiettivo**: conoscere per ogni lead se deriva da Facebook o Instagram, allineandosi all’export Magellano unificato.

Nei CSV di Magellano sono già presenti:

- `facebook_piattaforma` con valori `fb` / `ig`.
- `meta_campaign_id`, `meta_adset_id`, `meta_ad_id` per l’aggancio a Meta.

**Azioni:**

1. **Nuova migration Alembic** (stessa o separata, in base allo stile del repo):
   - Aggiungere a `Lead`:
     - `platform`: `String` o `Enum('facebook', 'instagram', 'unknown')`, nullable.
2. Aggiornare il modello `Lead` in `models.py` con il nuovo campo.

### 2.3 Mapping valori piattaforma

Definire una funzione di mapping **condivisa** (es. in un modulo `services/utils/platforms.py` o analogo) da usare sia negli import Magellano sia altrove:

```python
def normalize_platform(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    if v in ("fb", "facebook"):
        return "facebook"
    if v in ("ig", "instagram"):
        return "instagram"
    return "unknown"
```

---

## 3. Ingestion e sincronizzazione dati

### 3.1 Meta Graph API → `MetaMarketingData`

File coinvolto: `backend/services/integrations/meta_marketing.py`.

**Step:**

1. In `MetaMarketingService.get_insights`:
   - Aggiungere ai `fields` richiesti:
     - `publisher_platform`
     - `platform_position`
   - Nel `result.append(...)` includere:

     ```python
     "publisher_platform": insight.get("publisher_platform"),
     "platform_position": insight.get("platform_position"),
     ```

2. In `backend/services/sync/meta_marketing_sync.py`:
   - Nel loop che crea/aggiorna `MetaMarketingData` (sia in `run` che in `run_manual_sync`):
     - **Creazione**:

       ```python
       marketing_data = MetaMarketingData(
           ad_id=ad_record.id,
           date=insight_date,
           spend=insight["spend"],
           impressions=insight["impressions"],
           clicks=insight["clicks"],
           conversions=insight["conversions"],
           ctr=insight["ctr"],
           cpc=insight["cpc"],
           cpm=insight["cpm"],
           cpa=insight.get("cpa", 0),
           additional_metrics=insight.get("raw_data", {}),
           publisher_platform=insight.get("publisher_platform"),
           platform_position=insight.get("platform_position"),
       )
       ```

     - **Update** su record esistente:

       ```python
       existing.publisher_platform = insight.get("publisher_platform") or existing.publisher_platform
       existing.platform_position = insight.get("platform_position") or existing.platform_position
       ```

3. **Effetto sui dati storici**:
   - Il job utilizza già una logica "upsert" basata su `(ad_id, date)`.
   - Per popolare `publisher_platform`/`platform_position` su periodi passati:
     - eseguire un **sync manuale** (`run_manual_sync`) sul range desiderato,
     - oppure estendere la finestra del sync automatico per qualche settimana fino a completare la retro-compilazione.

### 3.2 Import Magellano → `Lead`

File coinvolti: `backend/scripts/magellano_export_step*.py` e/o `services/integrations/magellano_automation.py` (a seconda di dove viene scritto `Lead`).

**Step:**

1. Identificare i punti in cui si creano/aggiornano le `Lead` a partire dai CSV:
   - I CSV unificati contengono colonne come:
     - `facebook_piattaforma`
     - `meta_campaign_id`, `meta_adset_id`, `meta_ad_id`
2. Applicare `normalize_platform(facebook_piattaforma)` e assegnare il risultato a `Lead.platform`:

   ```python
   from services.utils.platforms import normalize_platform

   lead.platform = normalize_platform(row.get("facebook_piattaforma"))
   ```

3. Garantire che `Lead.meta_campaign_id`, `Lead.meta_adset_id`, `Lead.meta_ad_id` siano popolati (se non lo sono già) usando le colonne `meta_*` del CSV 0126.
4. Per i batch storici già importati:
   - se i file CSV sono ancora disponibili (come in `backend/exports/...`), valutare uno script di **re-import/migrazione** che:
     - rilegge gli export,
     - aggiorna solo `Lead.platform` (e i `meta_*` mancanti) nel DB, senza duplicare le lead.

---

## 4. Backend: filtro piattaforma nella vista `/marketing`

La vista gerarchica Marketing utilizza le seguenti API (file: `backend/services/api/ui/marketing.py`):

- `GET /api/marketing/campaigns`
- `GET /api/marketing/campaigns/{campaign_id}/adsets`
- `GET /api/marketing/adsets/{adset_id}/ads`
- `GET /api/marketing/adsets` (ricerca diretta per adset_name)
- `GET /api/marketing/ads` (ricerca diretta per ad_name)

### 4.1 Nuovo query param `platform`

**Definizione comune:**

- `platform` (string, opzionale):
  - `all` (default) → comportamento attuale, somma tutte le piattaforme.
  - `facebook`
  - `instagram`

Se il parametro non è passato o è `all`, **nessun filtro** su cui piattaforma applicare.

### 4.2 Applicazione del filtro ai dati Meta

Per ogni endpoint:

1. Leggere il parametro:

   ```python
   platform = request.query_params.get("platform", "all")
   ```

2. Quando si costruisce la query su `MetaMarketingData`:

   ```python
   marketing_data_query = (
       db.query(MetaMarketingData)
       .join(MetaAd)
       .join(MetaAdSet)
       # eventuali join campagna/account già presenti
       .filter(
           MetaMarketingData.date >= date_from_obj,
           MetaMarketingData.date <= date_to_obj,
           # altri filtri esistenti...
       )
   )

   if platform in ("facebook", "instagram"):
       marketing_data_query = marketing_data_query.filter(
           MetaMarketingData.publisher_platform == platform
       )

   marketing_data = marketing_data_query.all()
   ```

3. Tutti i KPI Meta (spend, impressions, conversions, CPL, ecc.) verranno automaticamente ricalcolati sul sottoinsieme di righe coerente con la piattaforma.

### 4.3 Applicazione del filtro alle Lead (Magellano / Ulixe)

Sempre per ciascun endpoint:

1. Quando si costruisce la query per le lead:

   ```python
   lead_query = db.query(Lead).filter(_lead_date_filter(date_from_obj, date_to_obj))
   # + eventuali filtri per meta_campaign_id, meta_adset_id, meta_ad_id

   if platform in ("facebook", "instagram"):
       lead_query = lead_query.filter(Lead.platform == platform)

   leads = lead_query.all()
   ```

2. Tutti i conteggi derivati (`magellano_entrate`, `magellano_inviate`, `magellano_scartate`, `ulixe_*`, `revenue`, `margine`, …) saranno calcolati solo sulle lead della piattaforma selezionata.
3. Lead storiche senza `platform` (NULL) verranno:
   - incluse solo quando `platform = all`,
   - escluse quando `platform = facebook` o `platform = instagram`.

### 4.4 Propagazione del parametro `platform` tra gli endpoint

Gli endpoint “diretti” (`/api/marketing/adsets` e `/api/marketing/ads`) devono accettare e propagare `platform` esattamente come `account_id`, `status`, `campaign_name`, ecc., applicando lo stesso schema di cui sopra alle query Meta e Lead.

---

## 5. Frontend `/marketing`: aggiunta del filtro piattaforma

File coinvolto: `frontend/templates/marketing.html`.

### 5.1 UI filtro piattaforma

1. Nella sezione filtri in alto, aggiungere un nuovo select:

   - Label: **Piattaforma**
   - Opzioni:
     - `value=""` → “Tutte le piattaforme” (mappato a `all` lato JS).
     - `value="facebook"` → “Facebook”.
     - `value="instagram"` → “Instagram”.

2. L’ID del select può essere, ad esempio, `platformFilter`.

### 5.2 Passaggio del parametro alle API

Nel JS esistente (funzioni come `loadAllCampaigns`, `loadAdsetsDirectly`, `loadAdsDirectly`, `loadAdsetsForCampaign`, `loadAdsForAdset`):

1. Leggere il valore del filtro:

   ```javascript
   const platform = document.getElementById("platformFilter").value || "all";
   ```

2. Aggiungerlo alle URL solo se diverso da `all` (per mantenere compatibilità con backend):

   ```javascript
   if (platform && platform !== "all") {
       url += `&platform=${platform}`;
   }
   ```

3. Applicare la stessa logica a tutte le chiamate fetch verso `/api/marketing/*`.

### 5.3 Comportamento atteso

- Default (`platformFilter` vuoto): equivale a `all`, vista identica all’attuale.
- Selezione **Facebook**:
  - Stessa gerarchia di righe (campagne/adset/ads), ma KPI ricalcolati solo per FB.
- Selezione **Instagram**:
  - Stessa logica, ma numeri solo per IG.

---

## 6. Backend `/marketing/analysis`: breakdown per piattaforma

File coinvolto:

- Route: `backend/services/api/ui/marketing.py` → funzione `marketing_analysis`.
- Template: `frontend/templates/marketing_analysis.html`.

### 6.1 Nuove strutture dati lato backend

All’interno di `marketing_analysis`, oltre a `totals`, `chart_points`, `distribution_points`, definire:

```python
platform_totals = {
    "facebook": {},
    "instagram": {},
}

platform_chart_points = {
    "facebook": [],
    "instagram": [],
}

platform_distribution_points = {
    "facebook": [],
    "instagram": [],
}
```

### 6.2 Calcolo KPI per piattaforma

Per ciascuna `platform` in `("facebook", "instagram")`:

1. **Dati Meta (KPI aggregati)**:
   - Copiare la logica con cui si calcolano oggi:
     - `total_spend`, `total_impressions`, `total_clicks`, `total_conversions`,
     - `avg_ctr`, `avg_cpc`, `avg_cpm`,
     - `global_cpl`.
   - Applicare alla query `marketing_rows` un filtro aggiuntivo:

     ```python
     query_p = base_query.filter(MetaMarketingData.publisher_platform == platform)
     marketing_rows_p = query_p.all()
     ```

   - Calcolare i KPI come per `totals`, salvando in `platform_totals[platform][...]`.

2. **Serie giornaliera**:
   - Copiare `daily_query` e aggiungere il filtro `MetaMarketingData.publisher_platform == platform`.
   - Popolare `platform_chart_points[platform]` con la stessa struttura di `chart_points`.

3. **Distribuzione periodo vs precedente**:
   - Copiare `current_dist_query`/`prev_dist_query` e aggiungere il filtro sulla piattaforma in entrambe.
   - Calcolare:
     - `total_spend_current_p`, `total_spend_prev_p`,
     - `total_leads_current_p`, `total_leads_prev_p`,
     - `cpl_current_agg_p`, `cpl_prev_agg_p`,
   - Salvare un singolo elemento in `platform_distribution_points[platform]`.

4. **Magellano / Ulixe per piattaforma**:
   - A partire da `campaign_ids`/`adset_ids` già calcolati, costruire una query `lead_query_p`:

     ```python
     lead_query_p = db.query(Lead).filter(_lead_date_filter(date_from, date_to))
     lead_query_p = lead_query_p.filter(Lead.meta_campaign_id.in_(campaign_ids))
     lead_query_p = lead_query_p.filter(Lead.platform == platform)
     leads_in_scope_p = lead_query_p.all()
     ```

   - Replicare la logica esistente usata per:
     - `total_magellano_entrate`,
     - `total_magellano_inviate`,
     - `total_magellano_scartate`,
     - `total_ulixe_approvate`,
     - `total_ulixe_scartate`,
     - `total_ricavo`, `total_margine`, `total_margine_pct`,
     - `pay_campagna`.
   - Salvare i risultati dentro `platform_totals[platform]["total_magellano_entrate"]`, ecc.

> Nota: il blocco esistente che popola `totals` non va modificato; la nuova sezione è un “overlay” di breakdown per piattaforma.

### 6.3 Passaggio al template

Nel `TemplateResponse` aggiungere:

```python
"platform_totals": platform_totals,
"platform_chart_points": platform_chart_points,
"platform_distribution_points": platform_distribution_points,
```

---

## 7. Frontend `/marketing/analysis`: UI per Facebook/Instagram

File: `frontend/templates/marketing_analysis.html`.

### 7.1 Card comparative FB / IG

Subito **sotto** le due righe di card globali esistenti:

1. Aggiungere una nuova sezione, ad esempio:

- Titolo o sottotitolo: “Breakdown per piattaforma”.
- Griglia 2 colonne (desktop) / 1 colonna (mobile), una card per:
  - **Facebook** (`platform_totals.facebook`).
  - **Instagram** (`platform_totals.instagram`).

2. Per ogni piattaforma, mostrare almeno:

- Ricavo, Speso, Margine, Margine %.
- Lead Meta e CPL medio.
- Lead entrate Magellano, Inviate WS, Approvate Ulixe.
- Scarto totale (da Meta a Ulixe).

3. Riutilizzare lo **stesso stile di formattazione** delle card globali:

- Formattazione valuta con `€` e virgola decimale.
- Colorazione Margine% (rosso / arancione / verde).
- Percentuali con `replace('.', ',')`.

### 7.2 Grafici per piattaforma

Utilizzando Chart.js già incluso per il grafico globale:

1. Aggiungere due nuove card grafico:

- “Facebook – Trend giornaliero Spend / CPL”.
- “Instagram – Trend giornaliero Spend / CPL”.

2. Ogni card con un `<canvas>` dedicato:

- `id="spendCplChartFacebook"`.
- `id="spendCplChartInstagram"`.

3. Nel blocco `<script>`:

- Convertire le liste Python in JSON tramite `|tojson`:

  ```javascript
  const platformChartPoints = {{ platform_chart_points|tojson }};
  ```

- Inizializzare due istanze Chart.js usando la stessa configurazione di `spendCplChart`, ma alimentandole con `platformChartPoints.facebook` e `platformChartPoints.instagram`.

4. (Facoltativo) Aggiungere due grafici di confronto periodo vs precedente per piattaforma, usando `platform_distribution_points`.

---

## 8. Edge case e decisioni

### 8.1 Campagne miste FB + IG

- Con `platform = all`:
  - KPI **globali** aggregano entrambe le piattaforme (comportamento attuale).
- Con `platform = facebook`:
  - Le campagne “pure IG” risultano a 0 e vengono escluse dai risultati (come già succede oggi per campagne a 0 spend/lead).
- Con `platform = instagram`:
  - Analogo discorso per campagne “pure FB”.

### 8.2 Dati storici senza piattaforma

- `Lead.platform` e `MetaMarketingData.publisher_platform` possono essere `NULL` per dati storici.
- Decisione:
  - `platform = all`: includere sia record con piattaforma nota sia quelli con piattaforma NULL (per non perdere storico).
  - `platform = facebook` / `platform = instagram`: considerare **solo** record con piattaforma esplicita.

### 8.3 Performance

- Filtrare per `publisher_platform` e `Lead.platform` è leggero se:
  - utilizzo di indici esistenti su `(ad_id, date)` e sulle chiavi Meta per join,
  - volume dati nei limiti attuali.
- Se emergono problemi di performance:
  - valutare un indice combinato su `(publisher_platform, date)` in `MetaMarketingData`.

---

## 9. Piano di rollout

### 9.1 Ordine consigliato

1. **Modello dati**:
   - Migration per `MetaMarketingData.publisher_platform` / `platform_position`.
   - Migration per `Lead.platform`.
2. **Ingestion**:
   - Aggiornare `get_insights` e il job di sync Meta.
   - Aggiornare import Magellano per popolare `Lead.platform` e (se necessario) i `meta_*`.
3. **Retro-compilazione dati**:
   - Eseguire un sync manuale Meta su un periodo rappresentativo (es. ultimi 60–90 giorni).
   - Script di re-import Magellano (opzionale) per riempire `Lead.platform` per storici rilevanti.
4. **Backend `/marketing`**:
   - Aggiungere parametro `platform` a tutte le API `/api/marketing/*`.
   - Applicare i filtri nelle query Meta e Lead.
5. **Frontend `/marketing`**:
   - Aggiungere select “Piattaforma”.
   - Propagare il parametro `platform` a tutte le fetch.
6. **Backend `/marketing/analysis`**:
   - Calcolare `platform_totals`, `platform_chart_points`, `platform_distribution_points`.
   - Passare le nuove strutture al template.
7. **Frontend `/marketing/analysis`**:
   - Aggiungere card comparative FB/IG.
   - Aggiungere grafici separati per piattaforma.
8. **Test e validazione**:
   - Verificare coerenza numeri tra:
     - `platform = all` vs somma FB+IG (tollerando piccole differenze dovute a record senza piattaforma).
     - `/marketing` e `/marketing/analysis` per stessi filtri.

### 9.2 Checklist di test funzionali

- [ ] `/marketing` senza selezione piattaforma → numeri identici alla versione pre-cambiamento.
- [ ] `/marketing` con `Piattaforma = Facebook`:
  - [ ] Nessuna lead con `facebook_piattaforma = ig` nei conteggi.
  - [ ] KPI Meta coerenti con report Ads Manager filtrato su Facebook.
- [ ] `/marketing` con `Piattaforma = Instagram`:
  - [ ] Idem sopra per IG.
- [ ] `/marketing/analysis`:
  - [ ] Card globali = somma (circa) di FB+IG.
  - [ ] Card “Facebook” mostrano solo dati FB.
  - [ ] Card “Instagram” mostrano solo dati IG.
  - [ ] Grafici FB/IG mostrano curve coerenti con l’andamento viste in Ads Manager per piattaforma.

---

## 10. Riferimenti incrociati

- `backend/services/api/ui/marketing.py`: route `/marketing`, `/marketing/analysis` e API `/api/marketing/*`.
- `backend/services/integrations/meta_marketing.py`: integrazione con Meta Graph API (campagne, adset, ads, insights).
- `backend/services/sync/meta_marketing_sync.py`: job di sincronizzazione dati Meta (`MetaMarketingData`).
- `backend/scripts/magellano_export_step*.py` + `backend/exports/*`: pipeline di import Magellano e CSV unificati con `facebook_piattaforma` e `meta_*`.
- `docs/marketing_prediction_implementation.md`: documento di riferimento per l’analisi e prediction marketing (utile per mantenere coerenza tra KPI).

