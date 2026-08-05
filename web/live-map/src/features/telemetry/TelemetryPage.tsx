import { useState } from 'react'
import { api } from '../../api/resources'
import { useApiResource } from '../../api/useApiResource'
import { useServerSnapshot } from '../../app/server'
import { date, duration, number } from '../../shared/format'
import { DataState, MetricGrid, PageHeader, Panel } from '../../shared/ui'
import { TelemetryChart } from './TelemetryChart'

export function TelemetryPage() {
  const [range, setRange] = useState('24h')
  const snapshot = useServerSnapshot()
  const history = useApiResource((signal) => api.history(range, signal), {
    key: `history-${range}`,
    intervalMs: 60_000
  })
  const stats = useApiResource((signal) => api.telemetryStats(signal), { key: 'telemetry-stats', intervalMs: 60_000 })
  const health = history.data?.fps_health

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Archivio prestazioni" title="Telemetria">
        FPS, frame time, campi base, continuità del flusso e presenze raccolte dal server.
      </PageHeader>
      <Panel
        title="FPS, giocatori e basi"
        eyebrow="Grafico storico"
        action={
          <label className="field-inline">
            Intervallo
            <select value={range} onChange={(event) => setRange(event.target.value)}>
              <option value="6h">6 ore</option>
              <option value="24h">24 ore</option>
              <option value="7d">7 giorni</option>
              <option value="30d">30 giorni</option>
              <option value="90d">90 giorni</option>
            </select>
          </label>
        }
      >
        <DataState
          loading={history.loading}
          error={history.error}
          onRetry={history.reload}
          hasData={Boolean(history.data)}
        >
          {history.data ? (
            <>
              <DataState
                loading={snapshot.loading}
                error={snapshot.error}
                onRetry={snapshot.reload}
                hasData={Boolean(snapshot.data)}
              >
                <MetricGrid
                  items={[
                    {
                      label: 'FPS medio',
                      value: number(snapshot.data?.summary_24h.average_fps, 1),
                      detail: 'ultime 24 ore',
                      tone: 'cyan'
                    },
                    {
                      label: 'FPS minimo',
                      value: number(snapshot.data?.summary_24h.minimum_fps, 1),
                      detail: 'ultime 24 ore'
                    },
                    {
                      label: 'Frame time',
                      value: `${number(snapshot.data?.metrics.serverframetime, 2)} ms`,
                      detail: 'valore corrente'
                    },
                    {
                      label: 'Picco online',
                      value: number(snapshot.data?.summary_24h.peak_players),
                      detail: 'ultime 24 ore'
                    },
                    {
                      label: 'Media online',
                      value: number(snapshot.data?.summary_24h.average_players, 1),
                      detail: 'ultime 24 ore'
                    },
                    {
                      label: 'Campi base',
                      value: number(snapshot.data?.metrics.basecampnum),
                      detail: 'valore corrente'
                    }
                  ]}
                />
              </DataState>
              <div className="health-readout" data-state={health?.state}>
                <div>
                  <span>STATO FPS / ULTIMA ORA</span>
                  <strong>{health?.label}</strong>
                </div>
                <div>
                  <span>PUNTEGGIO</span>
                  <strong>{health?.score == null ? '--' : `${number(health.score)} / 100`}</strong>
                </div>
                <p>
                  {health?.state === 'ok'
                    ? `Mediana ${number(health.median_fps, 1)} FPS · ultimi 10m ${number(health.recent_median_fps, 1)} · sotto 30 FPS ${number(health.under_30_percent, 1)}% · calo più lungo ${duration(health.longest_dip_seconds)}.`
                    : health?.state === 'calibrating'
                      ? `Copertura ${duration(health.coverage_seconds)}; servono almeno 5 minuti.`
                      : health?.state === 'stale'
                        ? `Il campione più recente ha ${duration(health.newest_sample_age_seconds)}: il giudizio è sospeso.`
                        : 'Il giudizio richiede campioni recenti sufficienti.'}
                </p>
              </div>
              <TelemetryChart samples={history.data.samples} timeWindow={history.data.window} />
            </>
          ) : null}
        </DataState>
      </Panel>
      <Panel title="Salute del flusso" eyebrow="Continuità e stabilità">
        <DataState loading={stats.loading} error={stats.error} onRetry={stats.reload} hasData={Boolean(stats.data)}>
          {stats.data ? (
            <>
              <MetricGrid
                items={[
                  { label: 'Uptime 24h', value: `${number(stats.data.uptime.pct_24h, 1)}%`, tone: 'green' },
                  { label: 'Uptime 7g', value: `${number(stats.data.uptime.pct_7d, 1)}%` },
                  { label: 'Stabilità FPS', value: stability(stats.data.fps.stability_cv_24h) },
                  { label: 'FPS medio 24h', value: number(stats.data.fps.mean_24h, 1) },
                  { label: 'Media online', value: number(stats.data.players.average_24h, 1) },
                  { label: 'Giorno mondo', value: number(stats.data.world.day) }
                ]}
              />
              <div className="gap-list">
                <h3>
                  Interruzioni del flusso / 24h <span>{stats.data.uptime.gap_count_24h}</span>
                </h3>
                <ul>
                  {stats.data.uptime.gaps_24h.map((gap) => (
                    <li key={gap.from}>
                      {date(gap.from)} · {duration(gap.seconds)}
                    </li>
                  ))}
                  {!stats.data.uptime.gaps_24h.length ? <li>Nessuna interruzione rilevata</li> : null}
                </ul>
              </div>
            </>
          ) : null}
        </DataState>
      </Panel>
    </div>
  )
}

function stability(value: number | null | undefined) {
  if (value == null) return '--'
  if (value <= 0.05) return 'Molto stabile'
  if (value <= 0.12) return 'Stabile'
  if (value <= 0.25) return 'Variabile'
  return 'Instabile'
}
