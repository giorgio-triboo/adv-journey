# Stati del Processo Magellano - Ulixe

Questo documento elenca tutti gli stati possibili per ogni fase del processo di gestione lead.

---

## Fase 1: Magellano (Caricamento Lead)

Quando le lead vengono caricate da Magellano (tramite upload manuale o sync automatico), vengono create con lo stato iniziale:

### Stato Iniziale
- **Stato**: `inviate WS Ulixe`
- **Categoria**: `IN_LAVORAZIONE`
- **Descrizione**: Lead appena importate da Magellano, pronte per essere inviate al sistema Ulixe

### Note
- Le lead esistenti vengono aggiornate (mantengono il loro stato attuale)
- Le lead nuove vengono create con questo stato iniziale
- Questo è uno stato intermedio che indica che la lead è stata inviata al cliente (Ulixe) ma non ha ancora ricevuto feedback

---

## Fase 2: Ulixe (Stati dal CRM)

Gli stati vengono recuperati dall'API Ulixe tramite il metodo `StatoLead` e categorizzati automaticamente dal sistema.

### Categoria: IN_LAVORAZIONE

Stati che indicano che la lead è ancora in lavorazione presso Ulixe:

- `In Lavorazione NV` - Ancora in gestione al numero verde, deve ancora essere inserito in CRM
- `Rif. N.V.` - Riferimento numero verde (senza "RIFIUTATO")

**Categoria Sistema**: `IN_LAVORAZIONE`

---

### Categoria: RIFIUTATO

Stati che indicano che la lead è stata rifiutata o scartata:

#### Stati Base
- `NO CRM` - Lead non inserita in CRM
- `RIFIUTATO NV` - Rifiutato al numero verde
- `Non interessato ai nostri servizi + [Data e Ora]` - Cliente non interessato
- `NO CRM SA` - NO CRM Servizio Accoglienza

#### Stati Dettagliati (NO CRM - RIFIUTATO NV - Rif. N.V.)
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Cerca altro`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Corso nn erogabile`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio ADL`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Beauty Academy`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Callegari`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Cepu`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Cepu Crediti`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio CepuCampus`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Cepuweb`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio CTR Stipulato-Non Definito`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Formass`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Già Iscritto`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Glo`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio GS`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio InCampus`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Master`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Open`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio SRE`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Stessa Lavorazione`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Stesso Brand`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Unich`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio UnieCampus`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Esigenza risolta`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - in lav. eCampus`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - in lav. Studium`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Inconsapevole della richiesta`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Italiano rich Lavoro`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Italiano senza requisiti`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Minorenne`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Minorenne Scherzo`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Non interessato ai nostri servizi`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Non più interessato`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Numero inesistente`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Numero nn corrisponde`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Numero straniero`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Recapiti errati`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Richiesta Lavoro`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Richiesta per errore`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Scherzo`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Senza Requisiti`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Sollecito`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Solo e-mail`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Straniero rich Lavoro`
- `NO CRM - RIFIUTATO NV - Rif. N.V. - Straniero senza requisiti`
- `NO CRM - ALTRO`

**Categoria Sistema**: `RIFIUTATO`

---

### Categoria: CRM (Intermedio)

Stati che indicano che la lead è stata inserita in CRM ma non ancora completata:

- `CRM` - Lead inserita in CRM
- `CRM + [Data e Ora]` - Lead in CRM con data/ora

**Categoria Sistema**: `CRM`

---

### Categoria: FINALE

Stati che indicano che la lead ha completato il processo con successo:

- `CRM - FISSATO` - Appuntamento fissato
- `CRM - SVOLTO` - Appuntamento svolto
- `CRM – ACCETTATO` - Lead accettata/completata

**Categoria Sistema**: `FINALE`

---

### Categoria: UNKNOWN

Stati non riconosciuti o errori:

- `ERROR` - Errore durante la chiamata API
- `Errore - Id Non Trovato` - ID lead non trovato in Ulixe
- Qualsiasi altro stato non riconosciuto dal sistema

**Categoria Sistema**: `UNKNOWN`

---

## Flusso degli Stati

```
Magellano Upload/Sync
    ↓
[inviate WS Ulixe] (IN_LAVORAZIONE)
    ↓
Sync Ulixe (controllo periodico)
    ↓
┌─────────────────────────────────────┐
│  Stati possibili da Ulixe:          │
│                                     │
│  • IN_LAVORAZIONE                   │
│    - In Lavorazione NV              │
│    - Rif. N.V.                      │
│                                     │
│  • RIFIUTATO                        │
│    - NO CRM                         │
│    - RIFIUTATO NV                   │
│    - NO CRM - RIFIUTATO NV - ...    │
│                                     │
│  • CRM (intermedio)                 │
│    - CRM                            │
│                                     │
│  • FINALE                           │
│    - CRM - FISSATO                  │
│    - CRM - SVOLTO                   │
│    - CRM - ACCETTATO                │
│                                     │
│  • UNKNOWN                          │
│    - ERROR                          │
│    - Stati non riconosciuti         │
└─────────────────────────────────────┘
```

---

## Logica di Categorizzazione

Il sistema categorizza automaticamente gli stati Ulixe secondo questa logica (implementata in `backend/services/integrations/ulixe.py`):

1. **RIFIUTATO**: Se contiene "NO CRM", "RIFIUTATO" o "NON INTERESSATO"
2. **IN_LAVORAZIONE**: Se contiene "IN LAVORAZIONE" o "RIF. N.V." (senza "RIFIUTATO")
3. **FINALE**: Se contiene "CRM" e ("SVOLTO", "ACCETTATO" o "FISSATO")
4. **CRM**: Se contiene "CRM" (ma non SVOLTO/ACCETTATO/FISSATO)
5. **UNKNOWN**: Tutti gli altri casi

---

## Note Tecniche

- Gli stati vengono aggiornati periodicamente tramite il job `ulixe_sync.py`
- Il sistema salva lo storico degli stati in `lead_history`
- Le lead con categoria `RIFIUTATO` non vengono più controllate automaticamente
- Il campo `current_status` contiene lo stato testuale completo da Ulixe
- Il campo `status_category` contiene la categoria normalizzata per filtri e statistiche
