# Zabbix 7.4 connector

Il sito riceve i valori direttamente dal processo `connector manager` di
Zabbix. Non usa la Zabbix API e non interroga Palworld.

## Prerequisiti

Nel file `zabbix_server.conf` deve essere attivo almeno un worker:

```ini
StartConnectors=1
```

Dopo la modifica riavvia Zabbix server. Il backlog e' monitorabile con la chiave
interna `zabbix[connector_queue]`.

Importa `palworld-server-site.yaml` e valorizza sul relativo host:

```text
{$PALAPISCHEME} protocollo REST, normalmente http
{$PALAPIIP}    indirizzo REST API Palworld raggiungibile da Zabbix
{$PALAPIPORT}  porta REST API Palworld, normalmente 8212
{$PALAPIKEY}   base64 di admin:<AdminPassword>, senza il prefisso Basic
```

Non collegare contemporaneamente il vecchio e il nuovo template allo stesso
host: entrambi eseguirebbero le medesime richieste REST.

Con il valore predefinito `http`, la Basic Auth viaggia in chiaro sulla rete.
Mantieni il traffico REST su LAN/VPN fidata oppure usa un proxy TLS davanti a
Palworld e imposta `{$PALAPISCHEME}=https`. La REST API non deve essere esposta
direttamente su Internet.

## Configurazione connector

Apri `Administration -> General -> Connectors` e crea un connector con:

```text
Name:                     Palworld Server Site
Data type:                Item values
URL:                      https://palworld.example.com:9443/api/v1/zabbix/ingest
Type of information:      All
Max records per message:  100
Concurrent sessions:      1
Attempts:                 5
Attempt interval:         5s
Timeout:                  10s
HTTP authentication:      Bearer
Bearer token:             stesso valore di ZABBIX_CONNECTOR_TOKEN
SSL verify peer:          attivo
SSL verify host:          attivo
Enabled:                  attivo
```

Aggiungi il filtro:

```text
Tag:       integration
Operator:  Equals
Value:     palworld-site
```

Il template applica questo tag ai cinque master item `status`, `info`, `metrics`,
`players` e `settings` e agli item calcolati `Site VM: ...`. I tag `dataset` e
`metric` presenti negli item permettono al receiver di riconoscere il contenuto
senza dipendere da item ID o nomi localizzati.

I tag configurati sull'host non vengono copiati in `item_tags` nei record di un
connector di tipo `Item values`: aggiungere `integration=palworld-site` soltanto
all'host non esporta quindi i template Linux e Docker. Reimporta invece
`zabbix/palworld-server-site.yaml` e aggiorna il template già collegato. Gli item
calcolati con chiave `palworld.site.vm.*` leggono le metriche dai template
ufficiali già presenti su `VM-PALWORLD` e hanno direttamente:

```text
integration=palworld-site
dataset=vm
metric=<identificatore canonico>
```

Sono esportati esclusivamente valori numerici allowlisted: CPU, memoria, load,
uptime, filesystem root, rete aggregata, raggiungibilità Docker, conteggi dei
container e uso aggregato CPU/memoria dei container. Il receiver rifiuta valori
testuali, log, metriche sconosciute e numeri non finiti. Payload grezzi Docker,
nomi container e valori arbitrari dei template non vengono conservati. La sola
diagnostica amministrativa conserva per 7 giorni fino a 10 nomi item ignorati
per batch, troncati e soltanto se provengono da `ZABBIX_SOURCE_HOST`.

I quattro master HTTP conservano un'ora di history. Zabbix non inoltra ai
connector gli item configurati con `History: Do not store`, quindi questo
intervallo minimo non deve essere azzerato. I payload grezzi restano quindi nel
database Zabbix per un'ora: limita l'accesso alla history agli amministratori.

Dopo aver salvato il connector, esegui sul server Zabbix:

```sh
zabbix_server -R config_cache_reload
```

Usa `Execute now` sugli item `Palworld: Info`, `Palworld: Settings` e sugli item
`Site VM: ...` per evitare di attendere il primo intervallo. La pagina **Stato
VM** mostra agli amministratori batch ricevuti, host sorgente, dataset,
accettati, ignorati, rifiutati e metriche ancora mancanti.

## Protocollo

Zabbix invia richieste `POST` con:

```http
Content-Type: application/x-ndjson
Authorization: Bearer <token>
```

La porta ingest accetta esclusivamente:

```text
GET  /healthz/
POST /api/v1/zabbix/ingest
```

La risposta `200` conferma il batch. `401`, `415` e `422` indicano errori
permanenti di autenticazione o formato. Il receiver usa `413` per un batch
troppo grande, ma Zabbix 7.4 puo' ritentare questo codice: mantieni quindi
`Max records per message` a 100. Gli errori temporanei restituiscono `503`.

## Sicurezza di rete

La porta HTTPS esterna del connector deve essere diversa da quella del sito.
Quando possibile limita la porta ingest all'indirizzo IP del server Zabbix nel
firewall o nel reverse proxy. Il Bearer token resta obbligatorio anche con
l'allowlist IP.
