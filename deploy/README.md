# Deploy insight-magellano su server con Docker

Configurazione per deploy su server (es. EC2 t4g) tramite Docker in modalità **single-stack**. Opzionalmente AWS CodeBuild/CodeDeploy.

## Requisiti sul server

- Docker e Docker Compose v2
- File `.env` nella root del progetto (creare da `deploy/.env.example` e `backend/.env.example`)
  - Obbligatori: `DATABASE_URL`, `SECRET_KEY`, `POSTGRES_PASSWORD`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`

### Porte

- **3000**: nginx (app principale)
- **Adminer**: accessibile solo a super-admin OAuth su path `/adminer/` (es. https://tuodominio/adminer/)

### Docker senza sudo (ec2-user)

```bash
sudo usermod -aG docker ec2-user
```

Poi esci e rientra in SSH (o `newgrp docker`).

### DNS in container di build

Se il build fallisce con "Temporary failure resolving 'deb.debian.org'", aggiungi in `/etc/docker/daemon.json`:

```json
{"dns": ["8.8.8.8", "8.8.4.4"]}
```

Poi `sudo systemctl restart docker`.

## Single-stack

- **backend**: singolo container applicativo.
- **nginx** sulla porta 3000: reverse proxy verso `backend`.
- Deploy semplice: build immagine, recreate backend/worker/scheduler.
- Possibile breve downtime durante update.

## Migrare DB locale → produzione

Per spostare i dati dal database locale in produzione (continuità):

```bash
./scripts/migrate_db_to_production.sh
```

Requisiti: Docker locale con `db` in esecuzione, SSH a `PROD_HOST` (default: ec2-user@magellano-insight.docker.aws.trd.local). Lo script esegue dump locale, copia sul server, ferma backend, restaura, riavvia.

## Deploy manuale

```bash
cd /home/ec2-user/insight-magellano
# backend/.env già configurato
./afterinstall.sh
```

## Deploy con AWS CodeDeploy

1. **ApplicationStop**: `scripts/stop.sh` ferma solo il worker.
2. **Copia file**: artefatto in `/home/ec2-user/insight-magellano`. `.env` non va nel repo.
3. **AfterInstall**: `afterinstall.sh` fa build, `up -d`, migrazioni Alembic.

- **appspec.yml**: destinazione `/home/ec2-user/insight-magellano`
- **buildspec.yml**: valida `backend/`, `deploy/`
- **scripts/stop.sh**: ferma solo worker (backend restano up)

## Avvio manuale stack

```bash
./deploy/scripts/start-stack.sh
```

Non serve più lo switch traffico blue/green: l’upstream nginx punta sempre a `backend`.

## Risorse (t4g.small)

- Celery worker con `--concurrency=1` (Playwright in sequenza)
- Solo Adminer
- Consigliata **t4g.medium** per carichi più alti

## Sviluppo locale (venv / Docker)

Stesso `backend/requirements.txt` usato dal build Docker: vedi **`../DEVELOPMENT.md`** nella root del repo (script `scripts/setup-local-venv.sh` e `docker compose`).
