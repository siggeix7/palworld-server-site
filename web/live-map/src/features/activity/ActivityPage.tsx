import { useState } from 'react'
import { useServerSnapshot } from '../../app/server'
import { date, number } from '../../shared/format'
import { DataState, PageHeader, Panel } from '../../shared/ui'

export function ActivityPage() {
  const [filter, setFilter] = useState<'all' | 'join' | 'leave'>('all')
  const snapshot = useServerSnapshot()
  const events = snapshot.data?.events || []
  const filtered = filter === 'all' ? events : events.filter((event) => event.type === filter)
  const joins = events.filter((event) => event.type === 'join').length

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Registro trasmissioni" title="Attività">
        Entrate e uscite degli esploratori osservate dalla telemetria più recente.
      </PageHeader>
      <Panel
        title="Attività recente"
        eyebrow="Eventi di presenza"
        action={
          <label className="field-inline">
            Filtro
            <select value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)}>
              <option value="all">Tutti</option>
              <option value="join">Entrate</option>
              <option value="leave">Uscite</option>
            </select>
          </label>
        }
      >
        <DataState
          loading={snapshot.loading}
          error={snapshot.error}
          onRetry={snapshot.reload}
          hasData={Boolean(snapshot.data)}
        >
          <p className="data-caption" role="status">
            {number(joins)} entrate · {number(events.length - joins)} uscite · {number(events.length)} totali
          </p>
          <ol className="event-feed">
            {filtered.map((event) => (
              <li key={`${event.timestamp}-${event.player_id}`} data-event={event.type}>
                <i />
                <span>
                  <strong>{event.player}</strong>{' '}
                  {event.type === 'join' ? 'è entrato nel mondo' : 'ha lasciato il mondo'}
                </span>
                <time dateTime={event.timestamp}>{date(event.timestamp)}</time>
              </li>
            ))}
            {!filtered.length ? <li className="empty-row">Nessun evento per il filtro selezionato.</li> : null}
          </ol>
        </DataState>
      </Panel>
    </div>
  )
}
