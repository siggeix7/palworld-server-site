import { IconArrowLeft } from '@tabler/icons-react'
import { Link, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { api } from '../../api/resources'
import { useApiResource } from '../../api/useApiResource'
import { date, duration, minutes, number } from '../../shared/format'
import { DataState, MetricGrid, PageHeader, Panel, StatusBadge } from '../../shared/ui'

const days = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']
const hours = Array.from({ length: 24 }, (_, hour) => String(hour).padStart(2, '0'))

export function PlayerPage() {
  const { publicId = '' } = useParams()
  const detail = useApiResource((signal) => api.player(publicId, signal), {
    key: `player-${publicId}`,
    intervalMs: 60_000
  })
  const data = detail.data

  if (detail.error instanceof ApiError && detail.error.status === 404 && !data) {
    return (
      <div className="page-stack">
        <Link className="back-link" to="/giocatori/">
          <IconArrowLeft aria-hidden="true" /> Torna ai giocatori
        </Link>
        <PageHeader eyebrow="Profilo non disponibile" title="Giocatore non trovato">
          Il profilo richiesto non esiste oppure non è più disponibile nell'archivio.
        </PageHeader>
      </div>
    )
  }

  return (
    <div className="page-stack">
      <Link className="back-link" to="/giocatori/">
        <IconArrowLeft aria-hidden="true" /> Torna ai giocatori
      </Link>
      <PageHeader
        eyebrow={data?.player.online ? 'Esploratore online' : 'Profilo esploratore'}
        title={data?.player.name || 'Giocatore'}
      >
        {data
          ? `${data.player.account_name || 'account non disponibile'} · ultimo accesso ${date(data.player.last_seen)}`
          : 'Caricamento del profilo.'}
      </PageHeader>
      <DataState loading={detail.loading} error={detail.error} onRetry={detail.reload} hasData={Boolean(data)}>
        {data ? (
          <>
            <div className="profile-status">
              <StatusBadge online={data.player.online} />
              {data.player.online ? <span>Sessione corrente {duration(data.player.current_session)}</span> : null}
            </div>
            <MetricGrid
              items={[
                { label: 'Livello', value: number(data.player.level), tone: 'cyan' },
                { label: 'Costruzioni', value: number(data.player.building_count) },
                { label: 'Tempo totale', value: minutes(data.player.minutes_lifetime) },
                { label: 'Sessioni', value: number(data.player.session_count_lifetime) },
                { label: 'Più lunga', value: minutes(data.player.longest_session_minutes) },
                {
                  label: 'Prima visita',
                  value: <time dateTime={data.player.first_seen}>{date(data.player.first_seen)}</time>
                }
              ]}
            />
            <Panel title="Presenza settimanale" eyebrow={`Media sulle ultime ${data.presence.weeks} settimane`}>
              <PresenceGrid grid={data.presence.grid} />
            </Panel>
            <Panel title="Qualità connessione" eyebrow="Campioni ping">
              <PingChart samples={data.ping} />
            </Panel>
            <div className="two-column">
              <Panel title="Sessioni recenti" eyebrow="Registro presenza">
                <ol className="session-list">
                  {data.sessions.map((session) => (
                    <li key={session.started_at}>
                      <span>
                        <time dateTime={session.started_at}>{date(session.started_at)}</time>{' '}
                        {session.active ? (
                          '· in corso'
                        ) : (
                          <>
                            → <time dateTime={session.ended_at || undefined}>{date(session.ended_at)}</time>
                          </>
                        )}
                      </span>
                      <strong>{minutes(session.duration_minutes)}</strong>
                    </li>
                  ))}
                  {!data.sessions.length ? <li className="empty-row">Nessuna sessione registrata.</li> : null}
                </ol>
              </Panel>
              <Panel title="Eventi" eyebrow="Trasmissioni personali">
                <ol className="event-feed compact">
                  {data.events.map((event) => (
                    <li key={`${event.timestamp}-${event.type}`} data-event={event.type}>
                      <i />
                      <span>{event.type === 'join' ? 'Entrata nel mondo' : 'Uscita dal mondo'}</span>
                      <time dateTime={event.timestamp}>{date(event.timestamp)}</time>
                    </li>
                  ))}
                  {!data.events.length ? <li className="empty-row">Nessun evento registrato.</li> : null}
                </ol>
              </Panel>
            </div>
          </>
        ) : null}
      </DataState>
    </div>
  )
}

export function PresenceGrid({ grid }: { grid: number[][] }) {
  const maximum = Math.max(1, ...grid.flat())
  const hasPresence = grid.some((row) => row.some((value) => value > 0))
  return (
    <>
      {!hasPresence ? (
        <p className="data-notice" role="status">
          Nessuna presenza registrata nel periodo.
        </p>
      ) : null}
      <div className="heatmap-scroll">
        <table className="heatmap-table presence-table">
          <caption className="sr-only">Minuti medi di presenza per giorno e ora</caption>
          <thead>
            <tr>
              <th scope="col">Giorno</th>
              {hours.map((hour) => (
                <th key={hour} scope="col">
                  {hour}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {days.map((dayLabel, day) => {
              const row = grid[day] || []
              return (
                <tr key={dayLabel}>
                  <th scope="row">{dayLabel}</th>
                  {hours.map((hourLabel, hour) => {
                    const value = row[hour] || 0
                    return (
                      <td
                        key={`${dayLabel}-${hourLabel}`}
                        className="presence-cell"
                        style={{ '--heat': `${Math.round((value / maximum) * 100)}%` } as React.CSSProperties}
                        aria-label={`${dayLabel}, ore ${hourLabel}:00: ${number(value)} minuti medi`}
                        tabIndex={value > 0 ? 0 : undefined}
                      >
                        {number(value)}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

function PingChart({ samples }: { samples: Array<{ timestamp: string; ping: number }> }) {
  if (samples.length < 2) return <p className="empty-row">Nessun campione di ping disponibile.</p>
  const width = 900
  const height = 220
  const values = samples.map((sample) => sample.ping)
  const observedMax = Math.max(...values)
  const scaleMax = Math.max(50, observedMax)
  const firstTime = new Date(samples[0].timestamp).getTime()
  const lastTime = new Date(samples.at(-1)?.timestamp || '').getTime()
  const span = Math.max(1, lastTime - firstTime)
  const points = samples
    .map((sample) => {
      const x = ((new Date(sample.timestamp).getTime() - firstTime) / span) * width
      return `${x},${height - (sample.ping / scaleMax) * (height - 20)}`
    })
    .join(' ')
  const average = values.reduce((total, value) => total + value, 0) / values.length
  return (
    <figure className="line-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="ping-title ping-description">
        <title id="ping-title">Andamento ping</title>
        <desc id="ping-description">
          {samples.length} campioni, media {number(average)} millisecondi, massimo osservato {number(observedMax)}.
        </desc>
        <line x1="0" y1={height - 1} x2={width} y2={height - 1} className="chart-axis" />
        <polyline points={points} className="chart-line ping" />
        <text x="0" y={height - 4} className="chart-label">
          {date(samples[0].timestamp)}
        </text>
        <text x={width} y={height - 4} textAnchor="end" className="chart-label">
          {date(samples.at(-1)?.timestamp)}
        </text>
      </svg>
      <figcaption>
        Media {number(average)} ms · massimo osservato {number(observedMax)} ms · {samples.length} campioni ·{' '}
        <time dateTime={samples[0].timestamp}>{date(samples[0].timestamp)}</time> →{' '}
        <time dateTime={samples.at(-1)?.timestamp}>{date(samples.at(-1)?.timestamp)}</time>
      </figcaption>
    </figure>
  )
}
