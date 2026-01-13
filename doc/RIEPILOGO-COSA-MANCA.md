# 📋 Riepilogo: Cosa Manca Ancora

## ✅ COMPLETATO RECENTEMENTE

1. ✅ **Riorganizzazione struttura progetto**
   - Separazione frontend/backend
   - Riorganizzazione services/ in 3 directory
   - 4 job autonomi separati
   - Docker configurato correttamente

2. ✅ **Scheduler sequenziale completo**
   - Pipeline 4 step funzionante
   - Logging e error handling

3. ✅ **Integrazione Meta Marketing**
   - Modelli DB, Service API, Interfaccia configurazione

---

## 🔴 PRIORITÀ ALTA - Funzionalità Core Mancanti

### 1. **Correlazione Automatica Lead ↔ Marketing** ⚠️
**Stato**: Modelli DB pronti, logica mancante

**Cosa serve**:
- Definire strategia di correlazione:
  - UTM parameters in Magellano?
  - Campaign ID matching?
  - Facebook Click ID (fbclid)?
  - Timestamp + IP matching?
- Implementare logica automatica per popolare:
  - `meta_campaign_id`
  - `meta_adset_id`
  - `meta_ad_id`
- Integrare nel flusso di sincronizzazione Magellano

**Blocchi**: Serve definire come vengono tracciate le lead da Meta in Magellano

---

### 2. **Vista Dettaglio Lead Estesa** ❌
**Stato**: Non implementata

**Cosa serve**:
- Pagina `/leads/{id}` con:
  - ✅ Dati anagrafici lead (già disponibili)
  - ❌ Storico lavorazioni Ulixe completo
  - ❌ Dati marketing correlati (campagna, adset, ad)
  - ❌ Metriche marketing (spend, ROI, CPL, etc.)
  - ❌ Timeline eventi marketing
  - ❌ Grafici performance (trend, distribuzione)

**Endpoint da creare**: `/api/leads/{id}/detail` o `/leads/{id}`

---

### 3. **Grafici Analytics** ⚠️
**Stato**: Dashboard base completa, grafici mancanti

**Cosa serve**:
- Grafici trend (spend, conversioni nel tempo)
- Grafici distribuzione (per campagna, adset, ad)
- Heatmap performance
- Confronto periodi

**Librerie suggerite**: Chart.js, Plotly, o ApexCharts

---

## 🟡 PRIORITÀ MEDIA - Miglioramenti Importanti

### 4. **Export e Report** ❌
**Stato**: Non implementato

**Cosa serve**:
- Export CSV/Excel con dati combinati:
  - Dati lead
  - Dati marketing
  - Storico lavorazioni
- Report periodici configurabili:
  - Giornaliero, settimanale, mensile
  - Template personalizzabili
- Alert configurabili:
  - CPL sopra soglia
  - Conversioni sotto soglia
  - Anomalie performance

---

### 5. **Logica Selezione Lead per Ulixe** ⚠️
**Stato**: Implementazione base (esclude solo "NO CRM")

**Cosa migliorare**:
- Criteri più sofisticati:
  - Data ultimo check (non controllare troppo spesso)
  - Stato attuale (priorità per alcuni stati)
  - Età lead (lead troppo vecchie?)
- Finestra temporale:
  - Max 1 mese per batch (per query molto grosse)
  - Query singole: nessun limite

---

### 6. **Update Magellano con Stati Ulixe** ⚠️
**Stato**: Non implementato (da fare quando necessario)

**Cosa serve**:
- Metodo `update_lead_status()` in `MagellanoService`
- Mapping stati Ulixe → valori Magellano
- Integrazione nel flusso scheduler (quando necessario)

**Nota**: Da implementare solo se serve effettivamente aggiornare Magellano

---

## 🟢 PRIORITÀ BASSA - Future Funzionalità

### 7. **Settings Avanzati Configurabili** ❌
**Stato**: Non implementato

**Cosa serve**:
- Sezione `/settings/advanced`:
  - Configurazione scheduler (orari, frequenze)
  - Configurazione rate limiting
  - Configurazione retention dati
  - Configurazione notifiche/alert
- Rimuovere hardcoding da backend
- Spostare configurazioni in DB

---

### 8. **Multi-tenant Configurabile** ❌
**Stato**: Preparazione futura

**Cosa serve**:
- Gestione brand/corsi multipli
- Isolamento dati per tenant
- Configurazione per tenant

**Nota**: Da implementare quando necessario

---

### 9. **Ottimizzazioni Performance** ❌
**Stato**: Non implementato

**Cosa serve**:
- Batch processing per grandi volumi
- Caching dati Meta (evitare chiamate duplicate)
- Retry logic con exponential backoff
- Circuit breaker per servizi esterni
- Indicizzazione DB per query veloci

---

## 📊 PRIORITÀ SUGGERITA

### Sprint Immediato (1-2 settimane)
1. **Correlazione Automatica Lead ↔ Marketing** (definire strategia + implementare)
2. **Vista Dettaglio Lead Estesa** (pagina completa con tutti i dati)

### Sprint Breve Termine (1 mese)
3. **Grafici Analytics** (trend, distribuzione, heatmap)
4. **Export CSV/Excel** (dati combinati)

### Sprint Medio Termine (2-3 mesi)
5. **Report Periodici** (configurabili, template)
6. **Alert Configurabili** (soglie, notifiche)
7. **Logica Selezione Lead Migliorata** (criteri sofisticati)

### Sprint Lungo Termine (quando necessario)
8. **Update Magellano** (solo se serve)
9. **Settings Avanzati** (configurazione completa)
10. **Multi-tenant** (quando necessario)
11. **Ottimizzazioni Performance** (batch, caching, retry)

---

## ❓ DOMANDE APERTE DA RISOLVERE

1. **Correlazione Lead ↔ Marketing**:
   - Come vengono tracciate le lead da Meta in Magellano?
   - C'è un campo in Magellano che identifica la campagna Meta?
   - UTM parameters disponibili?

2. **Update Magellano**:
   - Serve effettivamente aggiornare Magellano con stati Ulixe?
   - Quale API/metodo usare per l'update?

3. **Configurazione**:
   - Chi gestirà le configurazioni? (ruolo minimo richiesto?)
   - Serve audit log delle modifiche configurazione?

---

## 🎯 PROSSIMI PASSI IMMEDIATI

1. **Definire strategia correlazione Lead ↔ Marketing**
   - Analizzare dati Magellano disponibili
   - Identificare campo/campo per matching
   - Implementare logica automatica

2. **Implementare Vista Dettaglio Lead**
   - Endpoint API `/api/leads/{id}/detail`
   - Template HTML `/leads/{id}`
   - Integrare dati marketing e storico

3. **Aggiungere Grafici Analytics**
   - Scegliere libreria grafici
   - Implementare grafici trend
   - Implementare grafici distribuzione
