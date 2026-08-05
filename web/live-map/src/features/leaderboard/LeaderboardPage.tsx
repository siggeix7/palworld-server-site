import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/resources'
import { useApiResource } from '../../api/useApiResource'
import { date, minutes, number } from '../../shared/format'
import { DataState, PageHeader, Panel, StatusBadge } from '../../shared/ui'

type Range = '30d' | '365d' | 'all'

export function LeaderboardPage() {
  const [range, setRange] = useState<Range>('30d')
  const leaderboard = useApiResource((signal) => api.leaderboard(signal), { key: 'leaderboard', intervalMs: 60_000 })
  const entries = leaderboard.data?.by_playtime[range] || []

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Graduatoria esploratori" title="Classifica">
        Tempo trascorso nel mondo e livelli raggiunti dalla comunità.
      </PageHeader>
      <Panel
        title="Tempo di gioco"
        eyebrow="Presenza registrata"
        action={<RangeTabs value={range} onChange={setRange} />}
      >
        <DataState
          loading={leaderboard.loading}
          error={leaderboard.error}
          onRetry={leaderboard.reload}
          hasData={Boolean(leaderboard.data)}
        >
          <RankingTable
            entries={entries}
            value={(entry) =>
              minutes(range === '30d' ? entry.minutes_30d : range === '365d' ? entry.minutes_365d : entry.minutes_all)
            }
            valueLabel="Tempo"
            secondaryValue={(entry) => `Lv. ${number(entry.level)}`}
            secondaryLabel="Livello"
          />
        </DataState>
      </Panel>
      <Panel title="Livello massimo" eyebrow="Progressione personaggi">
        <DataState loading={leaderboard.loading} error={leaderboard.error} hasData={Boolean(leaderboard.data)}>
          <RankingTable
            entries={leaderboard.data?.by_level || []}
            value={(entry) => `Lv. ${number(entry.level)}`}
            valueLabel="Livello"
            secondaryValue={(entry) => minutes(entry.minutes_365d)}
            secondaryLabel="Tempo 365g"
          />
        </DataState>
      </Panel>
    </div>
  )
}

function RangeTabs({ value, onChange }: { value: Range; onChange: (range: Range) => void }) {
  return (
    <fieldset className="segmented">
      <legend className="sr-only">Intervallo classifica</legend>
      {(
        [
          ['30d', '30 giorni'],
          ['365d', '365 giorni'],
          ['all', 'Da sempre']
        ] as const
      ).map(([id, label]) => (
        <button type="button" key={id} aria-pressed={value === id} onClick={() => onChange(id)}>
          {label}
        </button>
      ))}
    </fieldset>
  )
}

interface Entry {
  id: string
  name: string
  account_name: string
  level: number
  online: boolean
  last_seen: string
  minutes_30d: number
  minutes_365d: number
  minutes_all: number
}

function RankingTable({
  entries,
  value,
  valueLabel,
  secondaryValue,
  secondaryLabel
}: {
  entries: Entry[]
  value: (entry: Entry) => string
  valueLabel: string
  secondaryValue: (entry: Entry) => string
  secondaryLabel: string
}) {
  return (
    <div className="table-scroll">
      <table className="data-table ranking-table">
        <thead>
          <tr>
            <th>Pos.</th>
            <th>Esploratore</th>
            <th>{valueLabel}</th>
            <th>{secondaryLabel}</th>
            <th>Ultimo accesso</th>
            <th>Stato</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry, index) => (
            <tr key={entry.id}>
              <td>
                <b className="rank-number">{String(index + 1).padStart(2, '0')}</b>
              </td>
              <td>
                <Link to={`/giocatori/${encodeURIComponent(entry.id)}/`}>
                  <strong>{entry.name}</strong>
                  <small>{entry.account_name || 'account non disponibile'}</small>
                </Link>
              </td>
              <td>
                <strong>{value(entry)}</strong>
              </td>
              <td>{secondaryValue(entry)}</td>
              <td>{date(entry.last_seen)}</td>
              <td>
                <StatusBadge online={entry.online} />
              </td>
            </tr>
          ))}
          {!entries.length ? (
            <tr>
              <td colSpan={6} className="empty-row">
                Nessun giocatore registrato.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  )
}
