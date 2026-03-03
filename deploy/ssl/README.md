# SSL/HTTPS (opzionale)

Di default nginx usa **solo HTTP** (porta 3000 sull'host → 80 interno), come in `deploy_exemple`.

Per servire HTTPS direttamente da nginx:

1. Copia in `deploy/ssl/`: `fullchain.pem` e `privkey.pem` (non committare `privkey.pem`).
2. Sostituisci `deploy/nginx/nginx.conf` con una config che ascolta 443 ssl e monta `/etc/nginx/ssl` (aggiungi il volume `./deploy/ssl:/etc/nginx/ssl:ro` al servizio nginx in `docker-compose.bluegreen.yml`).
3. Esponi la porta `3000:443` (o altra) nel compose.

Oppure termina SSL sul Load Balancer e lascia nginx in HTTP.
