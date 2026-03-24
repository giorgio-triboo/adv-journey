# Sviluppo locale (allineato alla produzione)

In produzione le dipendenze Python arrivano da **`backend/requirements.txt`** installate nel **Dockerfile** in fase di build. In locale puoi fare la stessa cosa in due modi.

## Opzione consigliata: Docker Compose

Stesso meccanismo della produzione: immagine con `pip install -r requirements.txt`.

```bash
# Dalla root del repo (dopo aver creato backend/.env da backend/.env.example)
docker compose build backend
docker compose up -d
```

L’API è su **http://localhost:8003** (vedi `docker-compose.yml`). Dopo un aggiornamento di `requirements.txt`:

```bash
docker compose build --no-cache backend && docker compose up -d backend
```

## Opzione senza Docker: virtualenv

Installa **le stesse** dipendenze del container in un venv nella root del repo:

```bash
chmod +x scripts/setup-local-venv.sh
./scripts/setup-local-venv.sh
```

Poi avvia l’API (working directory `backend`, come nel Dockerfile `WORKDIR /app`):

```bash
cd backend && ../.venv/bin/python -m uvicorn main:app --reload --host 0.0.0.0 --port 8003
```

Variabili d’ambiente: usa **`backend/.env`** (o esportale a mano); per Google Sheet RCRM servono le `ULIXE_RCRM_GOOGLE_SA_*` come in produzione.

## Perché vedevo `No module named 'google'`

Succede se avvii `uvicorn` con il Python di sistema (senza venv) o con un venv dove non hai mai eseguito `pip install -r backend/requirements.txt`. Lo script sopra risolve il caso venv.
