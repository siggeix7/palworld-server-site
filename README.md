# palworld-server-site

Dashboard pubblica, cartografia live e archivio telemetrico per un server
Palworld dedicato. I dati arrivano tramite un connector HTTP nativo di Zabbix
7.4: il sito non interroga direttamente Palworld e non possiede la password
amministrativa del server di gioco.

## Funzioni

- Stato online, freschezza del dato, versione e descrizione del server.
- Giocatori online, capacita' massima, FPS, frame time, uptime e giorno mondo.
- Mappa Palworld interattiva con coordinate esatte dei giocatori online.
- Zoom, trascinamento, selezione giocatore e traccia delle ultime 6 ore.
- Layer opzionali per viaggi rapidi e torri.
- Nome, account, livello, ping e numero di costruzioni per giocatore.
- Storico FPS e giocatori per 6 ore, 24 ore, 7, 30 o 90 giorni.
- Sessioni, ingressi, uscite e tempo online negli ultimi 7 giorni.
- Regole pubbliche del mondo divise per categoria.
- Layout responsive per desktop e mobile.
- Sanitizzazione prima della persistenza: IP, `userId`, `playerId`, password e
  porte amministrative non vengono conservati.
- Identificativi pubblici derivati con HMAC e non reversibili.
- Container con filesystem read-only, utente non privilegiato e health check.

L'endpoint Palworld `game-data` non e' necessario. L'API supportata `/players`
fornisce gia' le coordinate dei giocatori online. Senza `game-data` non e'
possibile visualizzare posizioni di basi, Pal, NPC, oggetti o costruzioni
individuali.

## Architettura e porte separate

Il container avvia due processi WSGI isolati:

```text
porta container 8000 -> dashboard e API pubbliche, nessun endpoint ingest
porta container 8001 -> receiver Zabbix, nessuna pagina pubblica
```

Flusso dei dati:

```text
Palworld REST API <- Zabbix HTTP Agent
                         |
                         | HTTPS NDJSON + Bearer token
                         v
                  porta ingest del sito
                         |
                         v
                 SQLite WAL in /data
                         |
                         v
                  porta web pubblica
```

Il refresh Palworld resta quello del template Zabbix: `metrics` e `players`
ogni 20 secondi. Il numero di visitatori del sito non aggiunge richieste al
server di gioco.

## Build

```sh
make build
```

Build e salvataggio dell'immagine in `/tmp`:

```sh
make save
```

Il file prodotto di default e':

```text
/tmp/palworld-server-site-latest.tar
```

Target disponibili:

```text
make build  crea palworld-server-site:latest
make save   crea anche l'archivio Docker in /tmp
make run    avvia entrambe le porte per sviluppo locale
make shell  apre una shell Django nel container
make test   esegue check, verifica migrazioni e test automatici
make clean  elimina l'archivio Docker in /tmp
```

Esempi:

```sh
make build TAG=v1.0.0
make save IMAGE=ghcr.io/example/palworld-server-site TAG=v1.0.0
```

## Docker Compose

Copia `.env.example` in `.env`, genera tre segreti differenti e scegli le due
porte host. Esempio completo:

```yaml
services:
  palworld-server-site:
    image: "${IMAGE:-palworld-server-site:latest}"
    build: .
    container_name: palworld-server-site
    restart: unless-stopped
    ports:
      # Sito pubblico: host 8080 -> container 8000
      - "${SITE_BIND:-0.0.0.0}:${SITE_PORT:-8080}:8000"
      # Ingest Zabbix: host 8081 -> container 8001
      - "${ZABBIX_INGEST_BIND:-127.0.0.1}:${ZABBIX_INGEST_PORT:-8081}:8001"
    environment:
      PUBLIC_SITE_URL: "${PUBLIC_SITE_URL}"
      DJANGO_ALLOWED_HOSTS: "${DJANGO_ALLOWED_HOSTS}"
      DJANGO_SECRET_KEY: "${DJANGO_SECRET_KEY}"
      PLAYER_HASH_SECRET: "${PLAYER_HASH_SECRET}"
      ZABBIX_CONNECTOR_TOKEN: "${ZABBIX_CONNECTOR_TOKEN}"
      ZABBIX_SOURCE_HOST: "${ZABBIX_SOURCE_HOST:-}"
      DJANGO_USE_X_FORWARDED_HOST: "true"
      DJANGO_SECURE_SSL_REDIRECT: "true"
      DJANGO_SECURE_HSTS_SECONDS: "86400"
      DATA_STALE_SECONDS: "90"
      POSITION_RETENTION_DAYS: "7"
      METRIC_RETENTION_DAYS: "90"
      TIME_ZONE: "Europe/Rome"
    volumes:
      - "${DATA_PATH:-/opt/palworld-server-site}:/data"
    read_only: true
    tmpfs:
      - /tmp:size=64m,mode=1777
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
```

Esempio `.env`:

```env
SITE_PORT=8080
SITE_BIND=0.0.0.0
ZABBIX_INGEST_PORT=8081
ZABBIX_INGEST_BIND=127.0.0.1
DATA_PATH=/opt/palworld-server-site

PUBLIC_SITE_URL=https://palworld.example.com:8443
DJANGO_ALLOWED_HOSTS=palworld.example.com,localhost,127.0.0.1
DJANGO_SECRET_KEY=generare-un-segreto-lungo-e-casuale
PLAYER_HASH_SECRET=generare-un-secondo-segreto-lungo-e-casuale
ZABBIX_CONNECTOR_TOKEN=generare-un-token-bearer-lungo-e-casuale
ZABBIX_SOURCE_HOST=nome-tecnico-host-zabbix

DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_SECURE_HSTS_SECONDS=86400
DATA_STALE_SECONDS=90
POSITION_RETENTION_DAYS=7
METRIC_RETENTION_DAYS=90
TIME_ZONE=Europe/Rome
```

Generazione dei segreti:

```sh
openssl rand -hex 48
openssl rand -hex 48
openssl rand -hex 48
```

Preparazione del volume e avvio, da eseguire soltanto quando si vuole realmente
pubblicare il servizio:

```sh
mkdir -p /opt/palworld-server-site
chown 1000:1000 /opt/palworld-server-site
docker compose up -d
```

## Reverse proxy HTTPS

Il container serve HTTP; TLS rimane responsabilita' del reverse proxy. Servono
due listener HTTPS separati, per esempio:

```text
https://palworld.example.com:8443 -> http://HOST_DOCKER:8080
https://palworld.example.com:9443 -> http://HOST_DOCKER:8081
```

La prima porta e' pubblica. La seconda e' destinata esclusivamente al connector
Zabbix e, se possibile, deve avere un'allowlist per l'IP del server Zabbix.
Il bind ingest predefinito e' `127.0.0.1`: cambialo con l'IP LAN del Docker host
o con `0.0.0.0` soltanto se il reverse proxy si trova su un'altra macchina,
aggiungendo in quel caso una regola firewall per il solo server Zabbix.
Entrambe devono inoltrare:

```text
Host
X-Forwarded-Host
X-Forwarded-Proto: https
X-Forwarded-For
```

La porta HTTPS non standard deve comparire sia in `PUBLIC_SITE_URL` sia nella
URL del connector. `DJANGO_ALLOWED_HOSTS` contiene solo il nome host, senza
schema e senza porta. Mantieni `localhost,127.0.0.1` per il health check interno.

## Zabbix 7.4

Il repository contiene:

```text
zabbix/palworld-server-site.yaml  template importabile
zabbix/connector.md               procedura completa del connector
```

Procedura sintetica:

1. Importa `zabbix/palworld-server-site.yaml`.
2. Sostituisci il vecchio template sul relativo host, senza collegarli insieme.
3. Configura `{$PALAPISCHEME}`, `{$PALAPIIP}`, `{$PALAPIPORT}` e il secret `{$PALAPIKEY}`.
4. Abilita `StartConnectors=1` in `zabbix_server.conf`.
5. Crea un connector di tipo `Item values`.
6. Usa `https://palworld.example.com:9443/api/v1/zabbix/ingest` come URL.
7. Seleziona autenticazione Bearer con `ZABBIX_CONNECTOR_TOKEN`.
8. Filtra `integration Equals palworld-site`.
9. Abilita entrambe le verifiche TLS.

Il connector manda batch NDJSON contenenti solo i cinque master item taggati:

```text
dataset=status
dataset=info
dataset=metrics
dataset=players
dataset=settings
```

Consulta [zabbix/connector.md](zabbix/connector.md) per retry, timeout e primo
caricamento dei dati.

L'API Palworld usa normalmente HTTP con Basic Auth. Base64 non cifra la
password amministrativa: il collegamento fra Zabbix e Palworld deve quindi
restare su LAN/VPN fidata. In alternativa anteponi un proxy TLS e imposta
`{$PALAPISCHEME}=https`. Non pubblicare mai la porta REST API su Internet.

`ZABBIX_SOURCE_HOST` e' opzionale ma consigliato: deve corrispondere al campo
tecnico `host` dell'host Zabbix e impedisce a un secondo server taggato nello
stesso modo di sovrascrivere la dashboard.

## Persistenza e retention

Il database SQLite usa modalita' WAL e vive in:

```text
/data/palworld-site.sqlite3
```

Il container puo' essere ricreato senza perdere storico. Le posizioni vengono
conservate per 7 giorni e metriche/eventi per 90 giorni. La pulizia avviene al
massimo una volta all'ora durante l'ingest.

I dati storici iniziano dal momento in cui il connector viene attivato. Il sito
non esegue backfill dalla Zabbix API.

## Endpoint

Porta web, container `8000`:

```text
GET /                              dashboard
GET /healthz/                      health check
GET /api/v1/snapshot              stato pubblico corrente
GET /api/v1/history?range=24h      storico telemetria
GET /api/v1/player/<id>/trail      traccia pubblica sanitizzata
```

Porta ingest, container `8001`:

```text
GET  /healthz/
POST /api/v1/zabbix/ingest
```

Una richiesta ingest inviata alla porta web restituisce `404`. La dashboard
richiesta sulla porta ingest restituisce `404`.

## Test locale senza Docker

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
make test
```

## Release container

Il workflow `.github/workflows/container-release.yml` esegue build e push su
GHCR per i tag `v*`, salva l'immagine come artifact e la allega alla GitHub
Release. E' configurato per un runner `self-hosted` Linux come `televideo-linux`.

## Note legali

Questo e' un progetto community non ufficiale. Palworld e la mappa appartengono
a Pocketpair, Inc. Coordinate, mappa V4 e punti statici derivano dal progetto
MIT `RNZ01/palworld-server-dashboard`; dettagli in [NOTICE.md](NOTICE.md). Prima
di distribuire pubblicamente l'immagine verifica che l'uso della mappa sia
compatibile con le linee guida fan-content applicabili al tuo sito.
