# Database Viewer

Interfaccia web per visualizzare e esplorare i dati del database PostgreSQL.

## Servizi Disponibili

### 1. Adminer (Porta 8080)
Tool PHP completo per la gestione del database.

**Accesso:**
- URL: http://localhost:8080
- Sistema: PostgreSQL
- Server: `db`
- Username: `user`
- Password: `password`
- Database: `cepudb`

### 2. Database Viewer Custom (Porta 8081)
Interfaccia web personalizzata con UI moderna per visualizzare i dati.

**Accesso:**
- URL: http://localhost:8081
- Visualizza tutte le tabelle del database
- Ricerca e paginazione
- Interfaccia responsive e moderna

## Funzionalità

- **Visualizzazione tabelle**: Lista di tutte le tabelle con conteggio record
- **Visualizzazione dati**: Tabella con tutti i dati, paginata
- **Ricerca**: Cerca in tutti i campi di testo della tabella
- **Formattazione JSON**: I campi JSON vengono formattati in modo leggibile
- **Responsive**: Interfaccia adattiva per mobile e desktop

## Avvio

I servizi vengono avviati automaticamente con:

```bash
docker-compose up -d
```

Per vedere i log:

```bash
docker-compose logs -f db_viewer
```

## API Endpoints

- `GET /api/tables` - Lista tutte le tabelle con statistiche
- `GET /api/table/<table_name>` - Dati di una tabella (JSON)
  - Query params: `page`, `per_page`, `search`
