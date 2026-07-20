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

Il template applica questo tag soltanto ai cinque master item `status`, `info`,
`metrics`, `players` e `settings`. Il campo `dataset` presente in ogni item
permette al receiver di riconoscere il contenuto senza dipendere da item ID o
nomi localizzati.

I quattro master HTTP conservano un'ora di history. Zabbix non inoltra ai
connector gli item configurati con `History: Do not store`, quindi questo
intervallo minimo non deve essere azzerato. I payload grezzi restano quindi nel
database Zabbix per un'ora: limita l'accesso alla history agli amministratori.

Dopo aver salvato il connector, esegui sul server Zabbix:

```sh
zabbix_server -R config_cache_reload
```

Usa `Execute now` sugli item `Palworld: Info` e `Palworld: Settings` per evitare
di attendere rispettivamente 30 minuti e 4 ore al primo avvio.

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
