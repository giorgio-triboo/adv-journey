# 🧪 Funzionalità da Testare

Questo documento elenca tutte le funzionalità implementate che necessitano di testing prima di essere considerate complete.

---

## A.1 - Maschera Lavorazioni

**Stato**: ✅ Implementato - ⚠️ DA TESTARE

**Endpoint**: `/lavorazioni` (GET con filtri)

**Cosa testare**:

### Filtri
- [ ] Filtro per stato lavorazione (in lavorazione, rifiutato, crm, finale)
- [ ] Filtro per periodo (data creazione, ultimo check)
- [ ] Filtro per campagna/account
- [ ] Ricerca per nome, cognome, email, telefono
- [ ] Combinazione di più filtri contemporaneamente

### Tabella Lead
- [ ] Visualizzazione corretta delle informazioni lead (nome, cognome, email, telefono)
- [ ] Visualizzazione stato attuale
- [ ] Visualizzazione data ultimo check
- [ ] Visualizzazione storico stati (timeline ultimi 3 stati)
- [ ] Visualizzazione campagna di provenienza
- [ ] Ordinamento per data ultimo check (più recenti prima)

### Statistiche Aggregate
- [ ] Calcolo corretto totale in lavorazione
- [ ] Calcolo corretto totale rifiutate
- [ ] Calcolo corretto totale CRM
- [ ] Calcolo corretto tasso conversione (finale / total * 100)
- [ ] Aggiornamento statistiche in base ai filtri applicati

### Performance
- [ ] Tempo di caricamento con molti lead (limite 500)
- [ ] Paginazione o scroll infinito (se implementato)

### UI/UX
- [ ] Layout responsive su mobile/tablet
- [ ] Messaggi di errore chiari in caso di problemi
- [ ] Feedback visivo durante caricamento

---

## A.2 - Maschera Marketing (Struttura Gerarchica)

**Stato**: ✅ Implementato - ⚠️ DA TESTARE

**Endpoint**: 
- `/marketing` (GET)
- `/api/marketing/campaigns` (GET)
- `/api/marketing/campaigns/{id}/adsets` (GET)
- `/api/marketing/adsets/{id}/ads` (GET)

**Cosa testare**:

### Struttura Gerarchica
- [ ] Dropdown account Meta funziona correttamente
- [ ] Selezione account carica lista campagne
- [ ] Selezione campagna carica lista adset
- [ ] Selezione adset carica lista creatività (ads)
- [ ] Reset dropdown quando si cambia livello superiore

### Metriche Aggregate
- [ ] Numero lead totali calcolato correttamente
- [ ] CPL Meta calcolato correttamente (spend / leads)
- [ ] Numero lead Magellano calcolato correttamente
- [ ] CPL Magellano (se disponibile)
- [ ] Numero lead Ulixe calcolato correttamente
- [ ] CPL Ulixe (se disponibile)
- [ ] Breakdown stati: NO CRM, Lavorazioni, OK

### Filtri Data
- [ ] Filtro data from/to funziona
- [ ] Metriche si aggiornano in base al periodo selezionato
- [ ] Default periodo (ultimi 30 giorni) funziona

### Tabella Dettagli
- [ ] Tabella mostra dati corretti per livello selezionato
- [ ] Colonne mostrano informazioni corrette
- [ ] Ordinamento funziona (se implementato)

### Performance
- [ ] Caricamento AJAX veloce e fluido
- [ ] Nessun errore in console browser
- [ ] Gestione errori API (404, 500, ecc.)

### UI/UX
- [ ] Card metriche sempre visibili e aggiornate
- [ ] Loading state durante caricamento dati
- [ ] Messaggi di errore chiari
- [ ] Layout responsive

---

## B) Settings Piattaforma - Riorganizzazione

**Stato**: ✅ Implementato - ⚠️ DA TESTARE

**Endpoint**: 
- `/settings/platform/users` (GET)
- `/settings/platform/users` (POST - aggiungi utente)
- `/settings/platform/users/role` (POST - aggiorna ruolo)
- `/settings/platform/users/delete` (POST - elimina utente)

**Cosa testare**:

### Accesso e Permessi
- [ ] Menu "Settings Piattaforma" visibile solo a super-admin
- [ ] Menu nascosto per admin/viewer
- [ ] Accesso diretto a `/settings/platform/users` reindirizza se non super-admin
- [ ] Messaggio errore chiaro se accesso negato

### Gestione Utenti
- [ ] Visualizzazione lista utenti corretta
- [ ] Aggiunta nuovo utente funziona
- [ ] Validazione email (formato corretto)
- [ ] Selezione ruolo (viewer, admin, super-admin)
- [ ] Aggiornamento ruolo utente funziona
- [ ] Eliminazione utente funziona
- [ ] Prevenzione auto-eliminazione
- [ ] Prevenzione auto-modifica ruolo

### Whitelist Automatica
- [ ] Login Google OAuth verifica presenza utente in DB
- [ ] Utente non in DB viene rifiutato
- [ ] Utente inattivo viene rifiutato
- [ ] Utente attivo può accedere

### Redirect Compatibilità
- [ ] Vecchio endpoint `/settings/users` reindirizza a `/settings/platform/users`
- [ ] Vecchi endpoint POST reindirizzano correttamente

### UI/UX
- [ ] Template `settings_platform_users.html` funziona correttamente
- [ ] Form action puntano agli endpoint corretti
- [ ] Feedback successo/errore visibile
- [ ] Layout responsive

---

## D.1 - Pagina Upload CSV/ZIP Magellano

**Stato**: ✅ Implementato - ⚠️ DA TESTARE

**Endpoint**: 
- `/settings/magellano/upload` (GET)
- `/api/magellano/upload` (POST)

**Cosa testare**:

### Upload File
- [ ] Upload file ZIP funziona
- [ ] Upload file XLS funziona
- [ ] Upload file XLSX funziona
- [ ] Upload file CSV funziona
- [ ] Validazione formato file (rifiuta formati non supportati)
- [ ] Validazione dimensione file (se implementato)

### Password Dinamica
- [ ] Calcolo password corretto: `ddmmyyyyT-Direct`
- [ ] Estrazione ZIP con password funziona
- [ ] Errore chiaro se password errata
- [ ] Gestione file multipli in ZIP

### Parsing File
- [ ] Parsing Excel (XLS/XLSX) corretto
- [ ] Parsing CSV corretto
- [ ] Gestione encoding (UTF-8, Latin-1, ecc.)
- [ ] Gestione colonne mancanti
- [ ] Gestione righe vuote

### Salvataggio DB
- [ ] Lead nuove vengono create correttamente
- [ ] Lead esistenti vengono aggiornate correttamente
- [ ] Campi opzionali gestiti correttamente (stringhe vuote, non zeri)
- [ ] Status iniziale impostato a "inviate WS Ulixe"
- [ ] Status category impostato a "IN_LAVORAZIONE"
- [ ] Messaggio UI indica correttamente "inviate al cliente" (stato intermedio)

### Feedback UI
- [ ] Messaggio successo con statistiche (imported, updated)
- [ ] Messaggio errore chiaro in caso di problemi
- [ ] Progress bar (se implementato)
- [ ] Loading state durante upload

### Campagna Opzionale
- [ ] Dropdown campagne funziona
- [ ] Selezione campagna opzionale funziona
- [ ] Associazione lead a campagna selezionata

---

## D.2 - Categorizzazione Stati Ulixe

**Stato**: ✅ Implementato - ⚠️ DA TESTARE

**Endpoint**: 
- Sync automatico tramite `ulixe_sync.py`
- `/api/leads/{lead_id}/check-ulixe` (POST - check manuale)

**Cosa testare**:

### Categorizzazione Stati
- [ ] Stato "In Lavorazione NV" categorizzato come `IN_LAVORAZIONE`
- [ ] Stato "Rif. N.V." categorizzato come `IN_LAVORAZIONE` (senza RIFIUTATO)
- [ ] Stati "NO CRM" categorizzati come `RIFIUTATO`
- [ ] Stati "RIFIUTATO NV" categorizzati come `RIFIUTATO`
- [ ] Stato "CRM" categorizzato come `CRM` (intermedio)
- [ ] Stato "CRM - FISSATO" categorizzato come `FINALE` ✅
- [ ] Stato "CRM - SVOLTO" categorizzato come `FINALE`
- [ ] Stato "CRM - ACCETTATO" categorizzato come `FINALE`
- [ ] Stati non riconosciuti categorizzati come `UNKNOWN`

### Sync Automatico
- [ ] Sync Ulixe esegue correttamente (scheduler)
- [ ] Lead con categoria `RIFIUTATO` non vengono più controllate
- [ ] Lead con categoria `IN_LAVORAZIONE`, `CRM`, `FINALE` vengono controllate periodicamente
- [ ] Storico stati salvato correttamente in `lead_history`
- [ ] Campo `last_check` aggiornato correttamente

### Check Manuale
- [ ] Endpoint `/api/leads/{lead_id}/check-ulixe` funziona
- [ ] Aggiornamento stato immediato dopo check manuale
- [ ] Storico aggiornato correttamente
- [ ] Gestione errori (lead senza external_user_id, errori API)

### Performance
- [ ] Rate limiting rispettato (0.5s tra chiamate)
- [ ] Sync non blocca il sistema
- [ ] Gestione errori non interrompe il processo

---

## F) Sistema Alert Email

**Stato**: ✅ Implementato - ⚠️ DA TESTARE

**Endpoint**: 
- `/settings/alerts` (GET)
- `/api/alerts` (POST - salva configurazione)
- `/api/alerts/test` (POST - test invio)

**Cosa testare**:

### Configurazione SMTP
- [ ] Salvataggio configurazione SMTP funziona
- [ ] Validazione campi obbligatori (host, port, user, password)
- [ ] Test connessione SMTP funziona
- [ ] Gestione errori connessione (host errato, credenziali errate, ecc.)

### Template Email
- [ ] Template HTML per alert renderizzato correttamente
- [ ] Template successo sync renderizzato correttamente
- [ ] Template errori critici renderizzato correttamente
- [ ] Variabili template sostituite correttamente

### Alert Magellano
- [ ] Alert successo inviato dopo sync Magellano
- [ ] Alert errore inviato in caso di problemi
- [ ] Dettagli corretti nell'email (numero lead, campagna, ecc.)

### Alert Ulixe
- [ ] Alert successo inviato dopo sync Ulixe
- [ ] Alert errore inviato in caso di problemi
- [ ] Dettagli corretti nell'email (lead controllate, aggiornate, errori)

### Alert Meta
- [ ] Alert successo inviato dopo sync Meta
- [ ] Alert errore inviato in caso di problemi
- [ ] Dettagli corretti nell'email (account, campagne, errori API)

### Configurazione Alert
- [ ] Disabilitare/abilitare alert per tipo (Magellano, Ulixe, Meta)
- [ ] Configurazione destinatari (email multiple)
- [ ] Salvataggio configurazione persistente

### Test Invio
- [ ] Pulsante "Test Email" funziona
- [ ] Email di test ricevuta correttamente
- [ ] Feedback successo/errore visibile

### Database
- [ ] Modello `AlertConfig` funziona correttamente
- [ ] Migration `add_alert_configs_table.py` applicata correttamente
- [ ] Dati salvati e recuperati correttamente

---

## I.2 - Healthcheck Esterno con Restart Automatico

**Stato**: ✅ Implementato - ⚠️ DA TESTARE

**Endpoint**: `/health` (GET)

**Cosa testare**:

### Healthcheck Endpoint
- [ ] Endpoint `/health` risponde correttamente
- [ ] Response JSON valida: `{"status": "ok", "timestamp": "...", "checks": {...}}`
- [ ] Verifica connessione DB funziona
- [ ] Status "ok" quando tutto funziona
- [ ] Status "degraded" quando DB non risponde
- [ ] Timestamp incluso nella response
- [ ] Dettagli check inclusi nella response

### Verifica Database
- [ ] Check DB rileva connessione attiva
- [ ] Check DB rileva disconnessione
- [ ] Messaggio errore chiaro se DB non disponibile
- [ ] Query test (`SELECT 1`) funziona

### Docker Healthcheck
- [ ] Dockerfile contiene `HEALTHCHECK` instruction
- [ ] Healthcheck Docker funziona (`docker ps` mostra status)
- [ ] Restart automatico Docker funziona (se configurato)
- [ ] Log healthcheck visibili

### Performance
- [ ] Healthcheck non impatta performance applicazione
- [ ] Tempo risposta < 1 secondo
- [ ] Nessun lock su DB durante check

### Integrazione
- [ ] Healthcheck utilizzabile da script esterni
- [ ] Response HTTP status code corretto (200 OK, 503 Service Unavailable)
- [ ] Compatibile con load balancer/monitoring tools

---

## 📝 Note Testing

### Ambiente di Test
- Testare in ambiente di sviluppo prima di produzione
- Verificare con dati reali e dati di test
- Testare edge cases (file vuoti, errori di rete, ecc.)

### Checklist Generale
- [ ] Tutti gli endpoint rispondono correttamente
- [ ] Validazione input funziona
- [ ] Gestione errori appropriata
- [ ] Messaggi utente chiari
- [ ] Performance accettabili
- [ ] Layout responsive
- [ ] Nessun errore in console browser
- [ ] Nessun errore in log backend

### Prossimi Passi Dopo Testing
1. Documentare eventuali bug trovati
2. Creare issue per correzioni necessarie
3. Aggiornare stato da "DA TESTARE" a "COMPLETATO" in TODO.md
4. Procedere con implementazione prossime funzionalità
