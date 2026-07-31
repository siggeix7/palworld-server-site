# Palworld Server Observatory

Dashboard Django riservata per un server dedicato Palworld. Il container legge
direttamente le REST API Palworld, sanitizza i payload prima della persistenza e
integra gli snapshot compatti estratti da `Level.sav` tramite lo script in
`ops/PalworldGuildSync`.

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
collector Django -> sanitizer -> SQLite -> sito autenticato :8000

Level.sav -> PalworldGuildSync -> API privata :8001 -> SQLite
                                      |
                                      +-> health e controllo collector
```

Il container avvia tre processi:

- Gunicorn pubblico su `8000` per pagine e API consultabili dagli utenti;
- Gunicorn privato su `8001` per health, stato collector e upload save;
- `manage.py runcollector` per interrogare direttamente Palworld.

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

- `userId`, `playerId`, `InstanceID`, `TrainerInstanceID`, `GuildID` e IP non
  vengono persistiti;
- gli identificativi necessari ai join diventano HMAC opachi con
  `PLAYER_HASH_SECRET`;
- password, indirizzi e impostazioni non in allowlist vengono scartati;
- da `game-data` restano solo oggetti mappa minimizzati e diagnostica aggregata;
- dallo script save arrivano solo identificativi opachi, aggregati e campi
  espressamente validati.

Usare secret distinti per `DJANGO_SECRET_KEY`, `PLAYER_HASH_SECRET` e
`PRIVATE_API_TOKEN`. Il file di produzione `.env` deve avere permessi `0600` e
non deve essere incluso nel repository.

## Configurazione

Creare `/opt/palworld-server-site/.env` partendo da `.env.example`. Variabili
principali:

```dotenv
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
```

`PALWORLD_API_URL` deve essere un'origine HTTP(S), senza credenziali, path,
query o fragment. Con HTTPS lasciare `PALWORLD_API_VERIFY_TLS=true` e installare
una catena di certificati attendibile nel container. Palworld espone normalmente
la REST API in HTTP: in quel caso `PALWORLD_API_ALLOW_INSECURE_HTTP=true` è un
opt-in obbligatorio e l'indirizzo deve essere raggiungibile esclusivamente su
LAN fidata o VPN, perché Basic Auth e payload non sono cifrati.

La configurazione completa, inclusi SMTP, accesso al server di gioco, retention
e privacy, è documentata direttamente in `.env.example`.

## Avvio e deploy

```bash
make test
make build TAG=<versione>
IMAGE=palworld-server-site:<versione> \
  docker compose --env-file /opt/palworld-server-site/.env up -d
```

Il volume configurato con `DATA_PATH` contiene database SQLite e lock del
collector. L'entrypoint applica automaticamente le migrazioni e abilita WAL.

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

`ops/PalworldGuildSync` contiene il job separato che legge `Level.sav`. Sul
server Palworld configurare almeno:

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

## API

Porta pubblica, autenticazione sito obbligatoria salvo health e pagine account:

```text
GET /healthz/
GET /api/v1/snapshot
GET /api/v1/history?range=24h
GET /api/v1/players
GET /api/v1/leaderboard
GET /api/v1/activity/heatmap?range=30d
GET /api/v1/map/heatmap?range=24h&map=palpagos
GET /api/v1/world/objects
GET /api/v1/telemetry/stats
GET /api/v1/world/diff
GET /api/v1/player/<public_id>/trail?range=6h
GET /api/v1/guild/data
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
```

Il target esegue i check Django, verifica che non manchino migrazioni e lancia
l'intera suite `dashboard`.
