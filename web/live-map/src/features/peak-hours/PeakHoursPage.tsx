import { useState } from 'react'
import { api } from '../../api/resources'
import { useApiResource } from '../../api/useApiResource'
import { minutes, number } from '../../shared/format'
import { DataState, MetricGrid, PageHeader, Panel } from '../../shared/ui'

const hours = Array.from({ length: 24 }, (_, hour) => String(hour).padStart(2, '0'))

export function PeakHoursPage() {
  const [range, setRange] = useState('30d')
  const heatmap = useApiResource((signal) => api.heatmap(range, signal), {
    key: `heatmap-${range}`,
    intervalMs: 120_000
  })
  const data = heatmap.data
  const maximum = Math.max(1, ...(data?.grid.flat() || [0]))

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Finestre operative" title="Orari di punta">
        Attività aggregata per giorno e ora, esplorabile anche con tastiera e lettori di schermo.
      </PageHeader>
      <DataState loading={heatmap.loading} error={heatmap.error} onRetry={heatmap.reload} hasData={Boolean(data)}>
        {data ? (
          <>
            <MetricGrid
              items={[
                {
                  label: 'Ora di picco',
                  value: data.peak_hour == null ? '--' : `${String(data.peak_hour).padStart(2, '0')}:00`,
                  tone: 'cyan'
                },
                { label: 'Giorno di picco', value: data.peak_day || '--' },
                { label: 'Sessioni', value: number(data.session_count) },
                { label: 'Tempo totale', value: minutes(data.total_minutes) }
              ]}
            />
            <Panel
              title="Matrice presenza 7 × 24"
              eyebrow="Minuti di attività"
              action={
                <label className="field-inline">
                  Periodo
                  <select value={range} onChange={(event) => setRange(event.target.value)}>
                    <option value="7d">7 giorni</option>
                    <option value="30d">30 giorni</option>
                    <option value="90d">90 giorni</option>
                  </select>
                </label>
              }
            >
              {!data.grid.some((row) => row.some((value) => value > 0)) ? (
                <p className="data-notice" role="status">
                  Nessun dato di attività nel periodo selezionato.
                </p>
              ) : null}
              <div className="heatmap-scroll">
                <table className="heatmap-table">
                  <caption className="sr-only">Minuti di presenza per giorno della settimana e ora</caption>
                  <thead>
                    <tr>
                      <th scope="col">Giorno</th>
                      {hours.map((hour) => (
                        <th scope="col" key={hour}>
                          {hour}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.grid.map((row, day) => (
                      <tr key={data.weekday_labels[day]}>
                        <th scope="row">{data.weekday_labels[day]}</th>
                        {hours.map((hourLabel, hour) => {
                          const value = row[hour] || 0
                          return (
                            <td
                              key={`${data.weekday_labels[day]}-${hourLabel}`}
                              className="heat-cell"
                              style={{ '--heat': `${Math.round((value / maximum) * 100)}%` } as React.CSSProperties}
                              aria-label={`${data.weekday_labels[day]}, ore ${hourLabel}:00: ${number(value, 1)} minuti`}
                              tabIndex={value > 0 ? 0 : undefined}
                            >
                              {number(value, value % 1 ? 1 : 0)}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </>
        ) : null}
      </DataState>
    </div>
  )
}
