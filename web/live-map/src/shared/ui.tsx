import { type ReactNode, useId } from 'react'
import { ApiError } from '../api/client'

export function PageHeader({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) {
  return (
    <header className="page-heading">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p>{children}</p>
    </header>
  )
}

export function Panel({
  title,
  eyebrow,
  action,
  children,
  className = ''
}: {
  title: string
  eyebrow?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  const generatedId = useId()
  const headingId = `panel-${generatedId.replaceAll(':', '')}`
  return (
    <section className={`dash-panel ${className}`} aria-labelledby={headingId}>
      <header className="panel-heading">
        <div>
          {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
          <h2 id={headingId}>{title}</h2>
        </div>
        {action}
      </header>
      {children}
    </section>
  )
}

export function MetricGrid({
  items
}: {
  items: Array<{ label: string; value: ReactNode; detail?: string; tone?: string }>
}) {
  return (
    <div className="metric-grid">
      {items.map((item) => (
        <article key={item.label} data-tone={item.tone}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
          {item.detail ? <small>{item.detail}</small> : null}
        </article>
      ))}
    </div>
  )
}

export function DataState({
  loading,
  error,
  onRetry,
  hasData,
  children
}: {
  loading: boolean
  error: Error | null
  onRetry?: () => void
  hasData: boolean
  children: ReactNode
}) {
  const staleDataAvailable = hasData
  if (loading && !staleDataAvailable)
    return (
      <p className="data-state" role="status">
        Sincronizzazione dati in corso...
      </p>
    )
  if (error && !staleDataAvailable) {
    return (
      <div className="data-state error" role="alert">
        <p>{error.message}</p>
        {onRetry ? (
          <button type="button" onClick={onRetry}>
            Riprova
          </button>
        ) : null}
        {error instanceof ApiError && error.actionUrl ? (
          <a className="text-link" href={error.actionUrl}>
            {error.actionLabel}
          </a>
        ) : null}
      </div>
    )
  }
  return (
    <>
      {error ? (
        <div className="data-notice error" role="status" aria-live="polite">
          <span>{error.message} Continuo a mostrare gli ultimi dati validi.</span>
          {onRetry ? (
            <button type="button" onClick={onRetry}>
              Riprova
            </button>
          ) : null}
        </div>
      ) : null}
      {children}
    </>
  )
}

export function StatusBadge({ online, stale = false }: { online: boolean; stale?: boolean }) {
  return (
    <span className={`status-badge ${online ? 'online' : ''} ${stale ? 'stale' : ''}`} role="status" aria-live="polite">
      {stale ? 'DATI OBSOLETI' : online ? 'ONLINE' : 'OFFLINE'}
    </span>
  )
}
