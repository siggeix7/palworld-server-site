# palworld-server-site

Dashboard riservata, cartografia live e archivio telemetrico per un server
Palworld dedicato. I dati arrivano tramite un connector HTTP nativo di Zabbix
7.4: il sito non interroga direttamente Palworld e non possiede la password
amministrativa del server di gioco.

## Funzioni

- Stato online, freschezza del dato, versione e descrizione del server.
- Giocatori online, capacita' massima, FPS, frame time, uptime e giorno mondo.
- Mappa Palworld interattiva con coordinate esatte dei giocatori online.
- Zoom ancorato al cursore, pan limitato, selezione e cluster di giocatori.
- Tracce selezionabili da 1 ora a 7 giorni e layer mappa persistenti.
- Layer opzionali per viaggi rapidi e torri.
- Nome, account, livello, ping e numero di costruzioni per giocatore.
- Storico FPS e giocatori per 6 ore, 24 ore, 7, 30 o 90 giorni.
- Grafico gap-aware e giudizio FPS sull'ultima ora calibrato sulla cadenza Zabbix.
- Sessioni, ingressi, uscite e tempo online negli ultimi 7 giorni.
- Archivio di tutti i giocatori con periodi online e minuti negli ultimi 30
  giorni, 365 giorni e da sempre.
- Scheda server con modalita', occupazione, avvio, piattaforme e funzioni attive.
- Regole pubbliche del mondo divise per categoria, incluso il crossplay.
- Ricerca impostazioni e giocatori, preferiti locali e colori giocatore stabili.
- Sette temi visuali persistenti, senza dipendenze frontend esterne.
- Layout responsive per desktop e mobile.
- Registrazione con verifica email, notifica agli amministratori, approvazione,
  revoca, eliminazione account e recupero password.
- Credenziali di gioco e guida di collegamento visibili soltanto ai membri
  verificati e approvati.
- Pagina VM con CPU, memoria, load, disco, rete, uptime e stato Docker.
- Diagnostica amministrativa dei batch connector, dataset mancanti, record
  ignorati/rifiutati e freschezza delle metriche.
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
porta container 8000 -> dashboard e API protette da login, nessun endpoint ingest
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
                  porta web protetta
```

Il refresh Palworld resta quello del template Zabbix: `metrics` e `players`
ogni 20 secondi. Il numero di visitatori del sito non aggiunge richieste al
server di gioco. Il polling browser si sospende quando la scheda non e' visibile
e applica un backoff progressivo in caso di errore.

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

Per sviluppo locale copia `.env.example` in `.env` con permessi `0600`. Genera
tre segreti differenti, configura SMTP, amministratori e credenziali di gioco,
quindi scegli le due porte host. Esempio completo:

```yaml
services:
  palworld-server-site:
    image: "${IMAGE:-palworld-server-site:latest}"
    container_name: palworld-server-site
    restart: unless-stopped
    ports:
      # Sito protetto: host 8080 -> container 8000
      - "${SITE_BIND:-127.0.0.1}:${SITE_PORT:-8080}:8000"
      # Ingest Zabbix: host 8081 -> container 8001
      - "${ZABBIX_INGEST_BIND:-127.0.0.1}:${ZABBIX_INGEST_PORT:-8081}:8001"
    environment:
      PUBLIC_SITE_URL: "${PUBLIC_SITE_URL}"
      DJANGO_ALLOWED_HOSTS: "${DJANGO_ALLOWED_HOSTS}"
      DJANGO_SECRET_KEY: "${DJANGO_SECRET_KEY}"
      PLAYER_HASH_SECRET: "${PLAYER_HASH_SECRET}"
      ZABBIX_CONNECTOR_TOKEN: "${ZABBIX_CONNECTOR_TOKEN}"
      ZABBIX_SOURCE_HOST: "${ZABBIX_SOURCE_HOST:?ZABBIX_SOURCE_HOST is required}"
      SITE_ADMIN_USERS: "${SITE_ADMIN_USERS}"
      AUTH_TRUSTED_PROXY_ADDRESSES: "${AUTH_TRUSTED_PROXY_ADDRESSES:-127.0.0.1,::1}"
      PALWORLD_PUBLIC_HOST: "${PALWORLD_PUBLIC_HOST}"
      PALWORLD_PUBLIC_PORT: "${PALWORLD_PUBLIC_PORT:-8211}"
      PALWORLD_PUBLIC_PASSWORD: "${PALWORLD_PUBLIC_PASSWORD}"
      EMAIL_HOST: "${EMAIL_HOST}"
      EMAIL_PORT: "${EMAIL_PORT:-465}"
      EMAIL_HOST_USER: "${EMAIL_HOST_USER}"
      EMAIL_HOST_PASSWORD: "${EMAIL_HOST_PASSWORD}"
      EMAIL_USE_SSL: "${EMAIL_USE_SSL:-true}"
      EMAIL_USE_TLS: "${EMAIL_USE_TLS:-false}"
      DEFAULT_FROM_EMAIL: "${DEFAULT_FROM_EMAIL}"
      DJANGO_USE_X_FORWARDED_HOST: "false"
      DJANGO_SECURE_SSL_REDIRECT: "true"
      DJANGO_SECURE_HSTS_SECONDS: "86400"
      DATA_STALE_SECONDS: "90"
      POSITION_RETENTION_DAYS: "7"
      METRIC_RETENTION_DAYS: "90"
      CONNECTOR_AUDIT_RETENTION_DAYS: "7"
      VM_DATA_STALE_SECONDS: "180"
      TIME_ZONE: "Europe/Rome"
    volumes:
      - "${DATA_PATH:-/opt/palworld-server-site/data}:/data"
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
SITE_BIND=127.0.0.1
ZABBIX_INGEST_PORT=8081
ZABBIX_INGEST_BIND=127.0.0.1
DATA_PATH=/opt/palworld-server-site/data

PUBLIC_SITE_URL=https://palworld.example.com:8443
DJANGO_ALLOWED_HOSTS=palworld.example.com,localhost,127.0.0.1
DJANGO_SECRET_KEY=generare-un-segreto-lungo-e-casuale
PLAYER_HASH_SECRET=generare-un-secondo-segreto-lungo-e-casuale
ZABBIX_CONNECTOR_TOKEN=generare-un-token-bearer-lungo-e-casuale
ZABBIX_SOURCE_HOST=VM-PALWORLD

SITE_ADMIN_USERS=admin@example.com
AUTH_TRUSTED_PROXY_ADDRESSES=127.0.0.1,::1
PALWORLD_PUBLIC_HOST=palworld.example.com
PALWORLD_PUBLIC_PORT=8211
PALWORLD_PUBLIC_PASSWORD=password-del-server-di-gioco

EMAIL_HOST=smtp.example.com
EMAIL_PORT=465
EMAIL_HOST_USER=mailer@example.com
EMAIL_HOST_PASSWORD=password-dell-account-email
EMAIL_USE_SSL=true
EMAIL_USE_TLS=false
EMAIL_TIMEOUT=15
DEFAULT_FROM_EMAIL=mailer@example.com

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

`EMAIL_HOST_PASSWORD` e `PALWORLD_PUBLIC_PASSWORD` sono segreti runtime: non
committarli. Con SMTP sulla porta 465 usa normalmente `EMAIL_USE_SSL=true` e
`EMAIL_USE_TLS=false`; per STARTTLS configura invece la porta prevista dal
provider, SSL disabilitato e TLS abilitato.

## Primo amministratore e membri

`PUBLIC_SITE_URL` deve essere un'origine HTTPS completa, senza percorso. I link
di verifica e recupero password usano esclusivamente questa origine e
l'applicazione rifiuta di avviarsi se non è valida.

`SITE_ADMIN_USERS` è obbligatorio e contiene username o email separati da
virgola, confrontati
senza distinzione fra maiuscole e minuscole. I valori con `@` sono sempre
interpretati come email; gli altri come username. Gli username registrabili non
possono contenere `@` e quelli indicati come amministratori sono riservati. Un
amministratore configurato tramite username deve quindi essere creato prima
dell'apertura delle registrazioni; per il primo avvio è consigliata l'email.
Per inizializzare il sito:

1. Configura in `SITE_ADMIN_USERS` l'email del primo amministratore.
2. Registra un account usando esattamente quell'indirizzo.
3. Apri il collegamento ricevuto via email e conferma esplicitamente nella
   pagina mostrata.
4. L'account viene abilitato automaticamente e può aprire **Membri** dalla
   dashboard.

Gli altri utenti devono verificare l'email e attendere l'approvazione. La revoca
ha effetto dalla richiesta successiva. Il pannello non consente di revocare un
amministratore configurato. Il gate della dashboard non è disattivabile tramite
variabili d'ambiente. Pagine e API protette inviano header `Cache-Control` che
ne vietano la memorizzazione.

Quando un utente verifica l'email, tutti gli amministratori configurati ricevono
una notifica con il collegamento al pannello membri. Un invio riuscito viene
registrato; in caso di errore SMTP il sito ritenta dalla pagina di attesa. Dal
pannello un amministratore può revocare l'accesso oppure eliminare definitivamente
un account non amministrativo dopo una seconda conferma.

Preparazione del volume e avvio, da eseguire soltanto quando si vuole realmente
pubblicare il servizio:

```sh
install -d -o 1000 -g 1000 /opt/palworld-server-site/data
install -m 644 docker-compose.yml /opt/palworld-server-site/docker-compose.yml
install -m 600 .env.example /opt/palworld-server-site/.env
# Sostituisci tutti i placeholder nel file .env prima dell'avvio.
chmod 600 /opt/palworld-server-site/.env
docker compose --env-file /opt/palworld-server-site/.env \
  -f /opt/palworld-server-site/docker-compose.yml up -d
```

Compose carica automaticamente `.env` solo dalla directory del progetto. Il
comando esplicito qui sopra evita di dipendere dalla directory corrente e
mantiene il file dei segreti escluso dal repository e dall'immagine.

Login, registrazione e invio email hanno limiti di frequenza condivisi nel
database. Applica comunque limiti anche sul reverse proxy, in particolare alle
route sotto `/accounts/`.

## Reverse proxy HTTPS

Il container serve HTTP; TLS rimane responsabilita' del reverse proxy. Servono
due listener HTTPS separati, per esempio:

```text
https://palworld.example.com:8443 -> http://HOST_DOCKER:8080
https://palworld.example.com:9443 -> http://HOST_DOCKER:8081
```

La prima porta e' raggiungibile dagli utenti ma richiede un account approvato.
La seconda e' destinata esclusivamente al connector Zabbix e, se possibile,
deve avere un'allowlist per l'IP del server Zabbix.
Il bind web predefinito è `127.0.0.1`, così il reverse proxy locale non può
essere aggirato. Usa un IP LAN o `0.0.0.0` soltanto per un proxy remoto e limita
la porta web al solo indirizzo del proxy tramite firewall.
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

Imposta `AUTH_TRUSTED_PROXY_ADDRESSES` con gli indirizzi sorgente del reverse
proxy così come sono visti dal container. Solo da questi indirizzi il limiter
accetta `X-Forwarded-For`; con un singolo proxy, sostituisci il valore ricevuto
dal client invece di fidarti di una catena arbitraria, per esempio in nginx con
`proxy_set_header X-Forwarded-For $remote_addr`.

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

Il connector manda batch NDJSON contenenti i cinque master item Palworld e gli
item calcolati numerici VM definiti nello stesso template:

```text
dataset=status
dataset=info
dataset=metrics
dataset=players
dataset=settings
dataset=vm, metric=<metrica canonica>
```

Un tag `integration` applicato soltanto all'host non viene ereditato dai valori
item del connector. Reimporta il template aggiornato: gli item `Site VM: ...`
leggono soltanto valori sorgente recenti dai template `Linux by Zabbix agent
active` e `Docker by Zabbix agent 2` e possiedono direttamente i tag richiesti.

Consulta [zabbix/connector.md](zabbix/connector.md) per retry, timeout e primo
caricamento dei dati.

L'API Palworld usa normalmente HTTP con Basic Auth. Base64 non cifra la
password amministrativa: il collegamento fra Zabbix e Palworld deve quindi
restare su LAN/VPN fidata. In alternativa anteponi un proxy TLS e imposta
`{$PALAPISCHEME}=https`. Non pubblicare mai la porta REST API su Internet.

`ZABBIX_SOURCE_HOST` e' obbligatorio: deve corrispondere esattamente al campo
tecnico `host` dell'host Zabbix. I record provenienti da host diversi vengono
ignorati e i relativi metadati non vengono conservati.

## Persistenza e retention

Il database SQLite usa modalita' WAL e vive in:

```text
/data/palworld-site.sqlite3
```

Il container puo' essere ricreato senza perdere storico. Le posizioni vengono
conservate per 7 giorni e metriche/eventi, incluse quelle VM, per 90 giorni. La
diagnostica dei batch connector viene conservata per 7 giorni. La pulizia
avviene al massimo una volta all'ora durante l'ingest.

I dati storici iniziano dal momento in cui il connector viene attivato. Il sito
non esegue backfill dalla Zabbix API.

## Endpoint

Porta web, container `8000`:

```text
GET /                              dashboard protetta
GET /vm/                           telemetria VM protetta
GET /healthz/                      health check
GET /api/v1/snapshot              stato corrente protetto
GET /api/v1/history?range=24h      storico telemetria protetto
GET /api/v1/players                archivio giocatori protetto
GET /api/v1/player/<id>/trail      traccia sanitizzata protetta
GET /api/v1/vm/snapshot            stato VM corrente protetto
GET /api/v1/vm/history?range=24h   storico VM protetto
GET /api/v1/connector/status       diagnostica connector, solo admin
```

`/healthz/`, registrazione, login, verifica email e recupero password restano
accessibili senza sessione. Le API protette rispondono `401` agli anonimi e
`403` agli account non ancora abilitati.

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

## Note legali

Questo e' un progetto community non ufficiale. Palworld e la mappa appartengono
a Pocketpair, Inc. Coordinate, mappa nativa 8192, punti statici e alcune
funzioni di interfaccia derivano dal progetto MIT
`RNZ01/palworld-server-dashboard` al commit
`588fa6390e0c5b6fe909e2c1fd3baddb86ef92c8`. Percorsi, modifiche, esclusioni,
hash degli asset e testo completo della licenza sono in [NOTICE.md](NOTICE.md).
Il notice e' disponibile anche dal footer del sito. La licenza MIT di RNZ01 non
copre gli asset Palworld: prima di ridistribuire la mappa verifica che l'uso sia
compatibile con le regole Pocketpair applicabili.
