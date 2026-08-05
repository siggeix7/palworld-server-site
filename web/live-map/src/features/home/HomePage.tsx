import { IconActivity, IconClock, IconKey, IconMap, IconPlanet, IconTrophy, IconUsers } from '@tabler/icons-react'
import { Link } from 'react-router-dom'
import { useServerSnapshot } from '../../app/server'
import { date, duration, number } from '../../shared/format'
import { DataState, MetricGrid, PageHeader, Panel, StatusBadge } from '../../shared/ui'

const sections = [
  ['/mappa/', 'Cartografia Palpagos', 'Mappa live', 'Posizioni, gilde, basi e punti di interesse.', IconMap],
  ['/telemetria/', 'Archivio prestazioni', 'Telemetria', 'FPS, continuità del flusso e presenze.', IconActivity],
  ['/giocatori/', 'Manifesto esploratori', 'Giocatori', 'Online, archivio e progressione.', IconUsers],
  ['/classifica/', 'Graduatoria', 'Classifica', 'Tempo di gioco e livelli raggiunti.', IconTrophy],
  ['/orari/', 'Finestre operative', 'Orari di punta', 'Presenze aggregate per giorno e ora.', IconClock],
  ['/accesso/', 'Accesso riservato', 'Entra nel server', 'Credenziali e guida di collegamento.', IconKey],
  ['/mondo/', 'Configurazione', 'Mondo', 'Regole attive e differenze vanilla.', IconPlanet]
] as const

export function HomePage() {
  const snapshot = useServerSnapshot()
  const data = snapshot.data
  const metrics = data?.metrics || {}
  const currentPlayers = Number(metrics.currentplayernum ?? data?.players.length ?? 0)
  const maxPlayers = Number(metrics.maxplayernum ?? 0)
  const dataAge = Number(data?.status.data_age_seconds ?? 120)

  return (
    <div className="page-stack home-page">
      <PageHeader eyebrow="Registro spedizione / accesso membri" title={data?.info.servername || 'Palworld Server'}>
        {data?.info.description || 'Centro di comando per la spedizione nelle isole Palpagos.'}
      </PageHeader>
      <DataState loading={snapshot.loading} error={snapshot.error} onRetry={snapshot.reload} hasData={Boolean(data)}>
        {data ? (
          <>
            <section className="command-hero">
              <div className="hero-server-copy">
                <StatusBadge online={data.status.online} stale={data.status.stale} />
                <p>
                  PALWORLD {data.info.version || '--'} / SEGNALE{' '}
                  {Math.max(0, 100 - Math.min(100, dataAge / 1.2)).toFixed(0)}%
                </p>
                <Link to="/mappa/" className="primary-action">
                  Apri cartografia live <span aria-hidden="true">↘</span>
                </Link>
              </div>
              <div className="radar-readout" role="status" aria-label="Segnale dati">
                <i
                  style={{ '--signal': `${Math.max(0, 100 - Math.min(100, dataAge / 1.2))}%` } as React.CSSProperties}
                />
                <strong>{data.status.data_age_seconds == null ? '--' : `${data.status.data_age_seconds}s`}</strong>
                <span>ETÀ SEGNALE</span>
              </div>
            </section>
            <MetricGrid
              items={[
                {
                  label: 'Esploratori',
                  value: `${number(currentPlayers)} / ${number(maxPlayers)}`,
                  detail: 'online / capacità',
                  tone: 'cyan'
                },
                { label: 'Server FPS', value: number(metrics.serverfps, 1), detail: 'frame al secondo', tone: 'green' },
                { label: 'Uptime', value: duration(metrics.uptime), detail: 'sessione server' },
                { label: 'Giorno mondo', value: number(metrics.days), detail: 'ciclo Palpagos' },
                { label: 'Picco 24h', value: number(data.summary_24h.peak_players), detail: 'giocatori' },
                { label: 'Media 24h', value: number(data.summary_24h.average_players, 1), detail: 'presenza media' },
                { label: 'Basi', value: number(metrics.basecampnum), detail: 'valore corrente' },
                { label: 'Ultimo dato', value: date(data.status.last_updated, true), detail: 'raccolta REST' }
              ]}
            />
            <div className="home-grid">
              <Panel
                title="Attività recente"
                eyebrow="Registro trasmissioni"
                action={
                  <Link className="text-link" to="/attivita/">
                    Apri registro attività ↘
                  </Link>
                }
              >
                <ol className="event-feed compact">
                  {data.events.slice(0, 6).map((event) => (
                    <li key={`${event.timestamp}-${event.player}`} data-event={event.type}>
                      <i />
                      <span>
                        <strong>{event.player}</strong> {event.type === 'join' ? 'è entrato' : 'è uscito'}
                      </span>
                      <time dateTime={event.timestamp}>{date(event.timestamp)}</time>
                    </li>
                  ))}
                  {!data.events.length ? <li className="empty-row">Nessun evento recente.</li> : null}
                </ol>
              </Panel>
              <nav className="section-matrix" aria-label="Sezioni osservatorio">
                {sections.map(([path, eyebrow, title, description, Icon]) => (
                  <Link to={path} key={path}>
                    <Icon aria-hidden="true" />
                    <span className="eyebrow">{eyebrow}</span>
                    <strong>{title}</strong>
                    <p>{description}</p>
                    <b>APRI ↘</b>
                  </Link>
                ))}
              </nav>
            </div>
          </>
        ) : null}
      </DataState>
    </div>
  )
}
