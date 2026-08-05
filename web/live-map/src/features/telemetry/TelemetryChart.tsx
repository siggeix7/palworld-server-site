import type { History } from '../../api/contracts'
import { date, number } from '../../shared/format'

export function TelemetryChart({
  samples,
  timeWindow
}: {
  samples: History['samples']
  timeWindow: History['window']
}) {
  const ordered = samples
    .filter((sample) => Number.isFinite(new Date(sample.timestamp).getTime()))
    .toSorted((left, right) => new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime())
  if (ordered.length < 2) return <p className="empty-row">Lo storico inizierà a popolarsi con il collector.</p>
  const width = 1000
  const height = 300
  const fps = ordered.map((sample) => sample.fps)
  const populations = ordered.flatMap((sample) => [sample.players, sample.bases])
  const minFps = Math.max(0, Math.min(...fps) - 5)
  const maxFps = Math.max(minFps + 5, Math.max(...fps) + 5)
  const maxPopulation = Math.max(1, ...populations)
  const firstTime = validTime(timeWindow.from) ?? new Date(ordered[0].timestamp).getTime()
  const lastTime = validTime(timeWindow.to) ?? new Date(ordered.at(-1)?.timestamp || '').getTime()
  const span = Math.max(1, lastTime - firstTime)
  const coordinates = (field: 'fps' | 'players' | 'bases', values: History['samples']) =>
    values
      .map((sample) => {
        const x = ((new Date(sample.timestamp).getTime() - firstTime) / span) * width
        const ratio = field === 'fps' ? (sample.fps - minFps) / (maxFps - minFps) : sample[field] / maxPopulation
        return `${x.toFixed(1)},${(height - ratio * (height - 20)).toFixed(1)}`
      })
      .join(' ')
  const segments = splitAtGaps(ordered)

  return (
    <figure className="line-chart telemetry-chart">
      <div className="chart-legend">
        <span data-line="fps">FPS</span>
        <span data-line="players">Giocatori</span>
        <span data-line="bases">Campi base</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="telemetry-title telemetry-description">
        <title id="telemetry-title">Storico FPS, giocatori e campi base</title>
        <desc id="telemetry-description">
          {ordered.length} campioni da {date(ordered[0].timestamp)} a {date(ordered.at(-1)?.timestamp)}. FPS da{' '}
          {number(Math.min(...fps), 1)} a {number(Math.max(...fps), 1)}.
        </desc>
        {[0, 1, 2, 3, 4].map((line) => (
          <line
            key={line}
            x1="0"
            y1={(line * height) / 4}
            x2={width}
            y2={(line * height) / 4}
            className="chart-gridline"
          />
        ))}
        {(['fps', 'players', 'bases'] as const).flatMap((field) =>
          segments.map((segment) => (
            <polyline
              key={`${field}-${segment[0].timestamp}`}
              points={coordinates(field, segment)}
              className={`chart-line ${field}`}
              data-series={field}
            />
          ))
        )}
        <text x="0" y={height - 4} className="chart-label">
          {date(new Date(firstTime).toISOString())}
        </text>
        <text x={width} y={height - 4} textAnchor="end" className="chart-label">
          {date(new Date(lastTime).toISOString())}
        </text>
      </svg>
      <figcaption>
        {ordered.length} campioni · FPS {number(Math.min(...fps), 1)}–{number(Math.max(...fps), 1)} · picco giocatori{' '}
        {number(Math.max(...ordered.map((sample) => sample.players)))}
      </figcaption>
      <details className="chart-data-table">
        <summary>Consulta i campioni in tabella</summary>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Data</th>
                <th>FPS</th>
                <th>Frame time</th>
                <th>Giocatori</th>
                <th>Basi</th>
              </tr>
            </thead>
            <tbody>
              {ordered.map((sample) => (
                <tr key={sample.timestamp}>
                  <td>
                    <time dateTime={sample.timestamp}>{date(sample.timestamp)}</time>
                  </td>
                  <td>{number(sample.fps, 1)}</td>
                  <td>{number(sample.frame_time, 2)} ms</td>
                  <td>{number(sample.players)}</td>
                  <td>{number(sample.bases)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  )
}

function validTime(value: string) {
  const parsed = new Date(value).getTime()
  return Number.isFinite(parsed) ? parsed : null
}

export function splitAtGaps(samples: History['samples']) {
  const segments: History['samples'][] = []
  for (const sample of samples) {
    if (!segments.length || sample.gap_before) segments.push([])
    segments.at(-1)?.push(sample)
  }
  return segments.filter((segment) => segment.length > 0)
}
