# Palworld Server Observatory

Dashboard Django riservata per un server dedicato Palworld, con interfaccia SPA
React/Vite. Il container legge direttamente le REST API Palworld, sanitizza i
payload prima della persistenza e integra gli snapshot compatti estratti da
`Level.sav` tramite lo script in `ops/PalworldGuildSync`.

## Funzioni

- Stato server, versione, descrizione, uptime e giorno del mondo.
- FPS, frame time, giocatori online e storico delle prestazioni.
- Mappa live con giocatori, basi, lavoratori, companion, NPC e Pal selvatici.
- Archivio presenze, sessioni, classifiche, heatmap e statistiche ping.
- Regole del mondo confrontate con i valori vanilla.
- Gilde, basi, progressione storica e avvisi derivati dal salvataggio.
- Registrazione, verifica email, approvazione amministrativa e accettazione
  delle condizioni d'uso.

## Architettura

```text
Palworld REST API
        |
        | Basic Auth, richieste in uscita dal container
        v
collector Django -> sanitizer -> PostgreSQL -> API Django -> SPA autenticata :8000

Level.sav -> PalworldGuildSync -> API privata :8001 -> PostgreSQL
                                      |
                                      +-> health e controllo collector
```

Il progetto Compose avvia PostgreSQL e il container applicativo. Quest'ultimo
avvia quattro processi:

- Gunicorn pubblico su `8000` per pagine e API consultabili dagli utenti;
- Gunicorn privato su `8001` per health, stato collector e upload save;
- `manage.py runcollector` per interrogare direttamente Palworld.
- `manage.py run_weekly_scheduler` per inviare i report settimanali secondo la
  pianificazione salvata nel database.

La porta privata non espone pagine, file statici o API pubbliche. Deve essere
pubblicata soltanto sulla rete amministrativa necessaria allo script save. Il
collector non richiede richieste in ingresso: contatta autonomamente l'origine
configurata in `PALWORLD_API_URL`.

## Raccolta REST

| Dataset | Endpoint Palworld | Intervallo |
| --- | --- | ---: |
| stato TCP | origine REST | 30 secondi |
| metriche | `/v1/api/metrics` | 20 secondi |
| giocatori | `/v1/api/players` | 20 secondi |
| game data | `/v1/api/game-data` | 15 secondi |
| informazioni | `/v1/api/info` | 30 minuti |
| impostazioni | `/v1/api/settings` | 4 ore |

Il collector usa timeout separati, non segue redirect, limita la dimensione di
ogni risposta e conserva l'ultimo snapshot valido quando un payload fallisce la
validazione. Un lock su `/data/palworld-collector.lock` impedisce l'avvio di due
collector sullo stesso volume.

## Privacy

I payload REST grezzi non vengono salvati. La sanitizzazione avviene prima di
ogni scrittura nel database:

- `userId`, `playerId`, `InstanceID`, `TrainerInstanceID` e `GuildID` non
  vengono persistiti; l'ultimo IP di gioco osservato viene conservato
  separatamente per sicurezza e moderazione ed è accessibile solo agli admin;
- per kick/ban, il pannello admin legge i `userId` raw direttamente dalla REST
  API Palworld solo on-demand; sono visibili esclusivamente agli admin e non
  vengono salvati nel database;
- gli identificativi necessari ai join diventano HMAC opachi con
  `PLAYER_HASH_SECRET`;
- password, indirizzi e impostazioni non in allowlist vengono scartati;
- da `game-data` restano solo oggetti mappa minimizzati e diagnostica aggregata;
- dallo script save arrivano snapshot pubblici minimizzati e, separatamente,
  materiale privato per la verifica del proprietario del personaggio;
- inventario, party e progressi privati non entrano nello snapshot pubblico e
  sono usati solo dagli endpoint di verifica/progresso senza cache.

Usare secret distinti per `DJANGO_SECRET_KEY`, `PLAYER_HASH_SECRET` e
`PRIVATE_API_TOKEN`. Il file di produzione `.env` deve avere permessi `0600` e
non deve essere incluso nel repository.

## Configurazione

Creare `/opt/palworld-server-site/.env` partendo da `.env.example`. Variabili
principali:

```dotenv
IMAGE=palworld-server-site:local
APP_BUILD_CONTEXT=./source
APP_PULL_POLICY=build
SITE_BIND=127.0.0.1
SITE_PORT=8080
PRIVATE_BIND=127.0.0.1
PRIVATE_PORT=8081
DATA_PATH=/opt/palworld-server-site/data

PUBLIC_SITE_URL=https://palworld.example.com:8443
DJANGO_ALLOWED_HOSTS=palworld.example.com,localhost,127.0.0.1
DJANGO_SECRET_KEY=...
PLAYER_HASH_SECRET=...
PRIVATE_API_TOKEN=...

PALWORLD_API_URL=https://palworld.example.com:8212
PALWORLD_API_USER=admin
PALWORLD_API_PASSWORD=...
PALWORLD_API_VERIFY_TLS=true
PALWORLD_API_ALLOW_INSECURE_HTTP=false
PALWORLD_API_CONNECT_TIMEOUT=3
COLLECTOR_LOCK_PATH=/data/palworld-collector.lock
AUTH_TRUSTED_PROXY_ADDRESSES=127.0.0.1,::1
```

`PALWORLD_API_URL` deve essere un'origine HTTP(S), senza credenziali, path,
query o fragment. Con HTTPS lasciare `PALWORLD_API_VERIFY_TLS=true` e installare
una catena di certificati attendibile nel container. Palworld espone normalmente
la REST API in HTTP: in quel caso `PALWORLD_API_ALLOW_INSECURE_HTTP=true` è un
opt-in obbligatorio e l'indirizzo deve essere raggiungibile esclusivamente su
LAN fidata o VPN, perché Basic Auth e payload non sono cifrati.

`AUTH_TRUSTED_PROXY_ADDRESSES` deve contenere soltanto gli indirizzi sorgente
dei reverse proxy direttamente connessi a Gunicorn. Il proxy deve sostituire,
non inoltrare ciecamente, `X-Forwarded-For`: il rate limit degli endpoint di
autenticazione usa l'indirizzo client più a destra solo per richieste provenienti
da questi proxy fidati.

La configurazione completa, inclusi SMTP, accesso al server di gioco, retention
e privacy, è documentata direttamente in `.env.example`.

## Avvio e deploy

```bash
make test
make build TAG=<versione>
IMAGE=palworld-server-site:<versione> \
  docker compose --env-file /opt/palworld-server-site/.env up -d
```

**Prerequisito permessi**: il container applicativo gira come uid 1000 e usa una
bind mount host per i lock. Prima del primo avvio creare directory e secret:

```bash
install -d -m 0700 -o 1000 -g 1000 /opt/palworld-server-site/data
install -d -m 0700 -o 999 -g 999 /opt/palworld-server-site/postgres-data
install -d -m 0700 /opt/palworld-server-site/{secrets,backups}
openssl rand -base64 48 > /opt/palworld-server-site/secrets/postgres-admin-password
openssl rand -base64 48 > /opt/palworld-server-site/secrets/postgres-app-password
chown root:root /opt/palworld-server-site/secrets/postgres-*-password
chmod 0444 /opt/palworld-server-site/secrets/postgres-*-password
```

I file sono leggibili nei container non root, ma la directory host `secrets`
resta `0700` e ciascun servizio monta soltanto i secret necessari.

`POSTGRES_DATA_PATH` contiene PostgreSQL; `DATA_PATH` contiene i lock applicativi
e conserva il vecchio SQLite durante la finestra di rollback. L'entrypoint
attende il database e applica automaticamente le migrazioni. PostgreSQL non
pubblica porte sull'host ed è raggiungibile soltanto sulla rete Docker interna.
Gli access log
non includono path o query string, così i token monouso presenti negli URL di
verifica e recupero password non vengono registrati.

### Migrazione da SQLite

Per il primo passaggio a PostgreSQL usare una copia coerente del database SQLite,
creata con la backup API SQLite dopo aver fermato il container applicativo.
Avviare solo `db`, applicare le migrazioni al database vuoto, quindi eseguire:

```bash
docker compose run --rm --no-deps \
  -e LEGACY_SQLITE_PATH=/data/palworld-site.sqlite3 \
  --entrypoint python3 palworld-server-site \
  web/manage.py migrate_sqlite_to_postgres --confirm-empty-target
```

Il comando verifica integrità SQLite, target vuoto, permessi Django, conteggi,
chiavi primarie e sequenze. Conservare SQLite finché la nuova versione non ha
superato la finestra di osservazione.

### Backup e trasferimento

Per backup portabili usare `pg_dump` in formato custom sotto
`/opt/palworld-server-site/backups`. È anche possibile fermare entrambi i
container e copiare tutta `/opt/palworld-server-site`: `.env`, Compose, `source/`,
`docker/`, `secrets/`, `data/` e `postgres-data/`. Con `APP_PULL_POLICY=build`,
`docker compose up -d` ricostruisce l'app da `source/` senza richiedere un
registry privato. Una copia fisica di `postgres-data` è
valida solo con PostgreSQL fermo, stessa major e stessa architettura; negli altri
casi usare `pg_dump` e `pg_restore`.

### Report settimanale

Il pannello `Admin` permette di abilitare l'invio, scegliere giorno, ora e fuso
IANA e vedere ultima e prossima esecuzione. Non installare un cron host parallelo:
lo scheduler interno anticipa la prossima occorrenza prima dell'invio, evitando
duplicazioni dopo un riavvio.

Verifiche locali:

```bash
curl -fsS http://127.0.0.1:8080/healthz/
curl -fsS http://127.0.0.1:8081/healthz/
docker inspect --format '{{.State.Health.Status}}' palworld-server-site
docker logs --since 10m palworld-server-site
```

Lo stato dettagliato richiede il bearer token privato:

```bash
curl -fsS -H "Authorization: Bearer $PRIVATE_API_TOKEN" \
  http://127.0.0.1:8081/api/v1/collector/status
```

## Sincronizzazione Save

`ops/PalworldGuildSync` contiene il job separato che legge `Level.sav` e i file
`Players/*.sav` nella stessa directory del mondo. Sul server Palworld
configurare almeno:

```dotenv
SITE_URL=https://<endpoint-privato>
SITE_TOKEN=<stesso valore di PRIVATE_API_TOKEN>
VERIFY_SSL=true
ALLOW_INSECURE_HTTP=false
SAVE_PATH=/percorso/al/mondo/Level.sav
```

Se l'upload resta in HTTP, limitarlo a una LAN fidata o VPN e non pubblicare la
porta privata su Internet: il bearer token e lo snapshot non sarebbero cifrati.

La procedura di installazione e il cron sono in
[`ops/PalworldGuildSync/README.md`](ops/PalworldGuildSync/README.md).

Il payload di schema 4 contiene le prove private in `claim.players`. Il listener
privato le salva separatamente dallo snapshot pubblico; gli identificativi raw
dei personaggi non vengono restituiti al browser.

## API

Porta pubblica, autenticazione sito obbligatoria salvo health e pagine account:

```text
GET /healthz/
GET /api/openapi.json
GET /api/v1/session
GET /api/v1/server/access
GET /api/v1/snapshot
GET /api/v1/history?range=24h
GET /api/v1/players
GET /api/v1/player/<public_id>
GET /api/v1/leaderboard
GET /api/v1/activity/heatmap?range=30d
GET /api/v1/world/objects
GET /api/v1/live-map/config
GET /api/v1/live-map/catalogue?v=<sha256>
GET /api/v1/live-map/players
GET /api/v1/live-map/objects
GET /api/v1/telemetry/stats
GET /api/v1/world/diff
GET /api/v1/guild/data
POST /api/v1/live-map/player-claims
POST /api/v1/live-map/player-claims/questions/cycle
POST /api/v1/live-map/player-claims/verify
GET /api/v1/live-map/me
GET /api/v1/live-map/me/progress
POST /api/v1/live-map/logout
```

Gli endpoint `live-map` per la verifica del personaggio sono disponibili solo
quando `PLAYER_CLAIMS_ENABLED=true`; usano token bearer temporanei e risposte
`private, no-store`.

Endpoint riservati agli utenti in `SITE_ADMIN_USERS` (sessione autenticata e
CSRF obbligatorio per i POST):

```text
GET  /api/v1/palworld/players
GET  /api/v1/admin/player-ips
GET  /api/v1/palworld/info
GET  /api/v1/palworld/admin/players
POST /api/v1/palworld/announce
POST /api/v1/palworld/kick
POST /api/v1/palworld/ban
POST /api/v1/palworld/unban
```

Porta privata:

```text
GET  /healthz/
GET  /api/v1/collector/status
POST /api/v1/guild/ingest
```

## Test

```bash
make test
cd web/live-map
npm ci
npm run generate:api
npm run check
npm test
npm run build
```

Il target `make test` esegue i check Django, verifica che non manchino migrazioni
e lancia l'intera suite `dashboard`. Il build Docker esegue anche generazione dei
tipi OpenAPI, lint, typecheck, test e build di produzione della SPA.
