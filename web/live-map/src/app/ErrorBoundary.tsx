import { Component, type ErrorInfo, type ReactNode } from 'react'

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Errore React non gestito', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <main className="fatal-error">
        <p className="eyebrow">Errore interfaccia</p>
        <h1>Il pannello non può essere visualizzato</h1>
        <p>I dati non sono stati modificati. Ricarica la pagina per riprovare.</p>
        <button type="button" onClick={() => window.location.reload()}>
          Ricarica
        </button>
      </main>
    )
  }
}
