import { IconCheck, IconCopy, IconEye, IconEyeOff, IconKey } from '@tabler/icons-react'
import { useState } from 'react'
import { api } from '../../api/resources'
import { useApiResource } from '../../api/useApiResource'
import { DataState, PageHeader, Panel } from '../../shared/ui'

export function AccessPage() {
  const access = useApiResource((signal) => api.access(signal), { key: 'server-access', clearOnError: true })
  const [revealed, setRevealed] = useState(false)
  const [copied, setCopied] = useState('')
  const [copyError, setCopyError] = useState(false)
  const data = access.data
  const address = data?.address || ''

  const copy = async (key: string, value: string) => {
    if (!value) return
    try {
      await navigator.clipboard.writeText(value)
      setCopyError(false)
      setCopied(key)
      window.setTimeout(() => setCopied(''), 1400)
    } catch {
      setCopyError(true)
    }
  }

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Accesso riservato ai membri" title="Entra nel server">
        Credenziali operative e sequenza di collegamento. Non condividerle pubblicamente.
      </PageHeader>
      <DataState loading={access.loading} error={access.error} onRetry={access.reload} hasData={Boolean(data)}>
        {data ? (
          <div className="access-grid">
            <Panel title="Coordinate di accesso" eyebrow="Canale multiplayer" className="credential-panel">
              <Credential
                label="Indirizzo pubblico"
                value={data.host || 'Non configurato'}
                onCopy={() => copy('host', data.host || '')}
                copied={copied === 'host'}
              />
              <Credential
                label="Porta di gioco"
                value={String(data.port)}
                onCopy={() => copy('port', String(data.port))}
                copied={copied === 'port'}
              />
              <div className="credential-line">
                <span>Password</span>
                <code>{data.password ? (revealed ? data.password : '••••••••') : 'Non configurata'}</code>
                <button
                  type="button"
                  disabled={!data.password}
                  aria-pressed={revealed}
                  aria-label={revealed ? 'Nascondi password del server' : 'Mostra password del server'}
                  onClick={() => setRevealed((value) => !value)}
                >
                  {revealed ? <IconEyeOff aria-hidden="true" /> : <IconEye aria-hidden="true" />}
                  <span>{revealed ? 'Nascondi' : 'Mostra'}</span>
                </button>
                <button
                  type="button"
                  disabled={!data.password}
                  aria-label="Copia password del server"
                  onClick={() => copy('password', data.password || '')}
                >
                  {copied === 'password' ? <IconCheck aria-hidden="true" /> : <IconCopy aria-hidden="true" />}
                  <span>{copied === 'password' ? 'Copiata' : 'Copia'}</span>
                </button>
              </div>
              <Credential
                label="Indirizzo completo"
                value={address || 'Non configurato'}
                onCopy={() => copy('address', address)}
                copied={copied === 'address'}
              />
              {!data.configured ? (
                <p className="data-notice warning" role="alert">
                  Configurazione incompleta: indirizzo, porta o password del server non sono ancora disponibili.
                </p>
              ) : null}
              {copyError ? (
                <p className="error-text" role="status">
                  Copia non disponibile in questo browser.
                </p>
              ) : null}
            </Panel>
            <Panel title="Sequenza di collegamento" eyebrow="Guida rapida">
              <ol className="procedure-list">
                <li>
                  <b>01</b>
                  <span>
                    Avvia Palworld e seleziona <strong>Partecipa a una partita multigiocatore</strong>.
                  </span>
                </li>
                <li>
                  <b>02</b>
                  <span>
                    Inserisci l'indirizzo completo <strong>IP:porta</strong> nel campo in basso.
                  </span>
                </li>
                <li>
                  <b>03</b>
                  <span>
                    Premi <strong>Connetti</strong> e inserisci la password quando richiesta.
                  </span>
                </li>
                <li>
                  <b>04</b>
                  <span>Aggiungi il server ai recenti o ai preferiti per il prossimo accesso.</span>
                </li>
              </ol>
              <p className="callout">
                <IconKey aria-hidden="true" /> In caso di errore verifica di usare la porta di gioco, non la porta REST
                API.
              </p>
            </Panel>
          </div>
        ) : null}
      </DataState>
    </div>
  )
}

function Credential({
  label,
  value,
  onCopy,
  copied
}: {
  label: string
  value: string
  onCopy: () => void
  copied: boolean
}) {
  return (
    <div className="credential-line">
      <span>{label}</span>
      <code>{value}</code>
      <button
        type="button"
        disabled={value.startsWith('Non configurat')}
        aria-label={`Copia ${label.toLocaleLowerCase('it')}`}
        onClick={onCopy}
      >
        {copied ? <IconCheck aria-hidden="true" /> : <IconCopy aria-hidden="true" />}
        <span>{copied ? 'Copiato' : 'Copia'}</span>
      </button>
    </div>
  )
}
