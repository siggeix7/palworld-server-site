import { IconAlertTriangle, IconCalendarTime, IconRefresh, IconSend, IconShieldLock } from '@tabler/icons-react'
import { type FormEvent, useEffect, useState } from 'react'
import { api } from '../../api/resources'
import { useApiResource } from '../../api/useApiResource'
import { sessionIsAdmin, useSession } from '../../app/session'
import { date, number } from '../../shared/format'
import { DataState, PageHeader, Panel, StatusBadge } from '../../shared/ui'

export function AdminPage() {
  const session = useSession()
  const adminEnabled = sessionIsAdmin(session)
  const players = useApiResource((signal) => api.adminPlayers(signal), {
    key: 'admin-players',
    intervalMs: 20_000,
    enabled: adminEnabled,
    clearOnError: true
  })
  const ips = useApiResource((signal) => api.adminIps(signal), {
    key: 'admin-ips',
    intervalMs: 60_000,
    enabled: adminEnabled,
    clearOnError: true
  })
  const info = useApiResource((signal) => api.adminInfo(signal), {
    key: 'admin-info',
    intervalMs: 60_000,
    enabled: adminEnabled,
    clearOnError: true
  })
  const commands = useApiResource((signal) => api.commandPlayers(signal), {
    key: 'admin-commands',
    intervalMs: 60_000,
    enabled: adminEnabled,
    clearOnError: true
  })
  const guilds = useApiResource((signal) => api.guilds(signal), {
    key: 'admin-alerts',
    intervalMs: 120_000,
    enabled: adminEnabled,
    clearOnError: true
  })
  const weeklySchedule = useApiResource((signal) => api.weeklyReportSchedule(signal), {
    key: 'admin-weekly-report-schedule',
    intervalMs: 60_000,
    enabled: adminEnabled,
    clearOnError: true
  })
  const [message, setMessage] = useState('')
  const [unbanId, setUnbanId] = useState('')
  const [scheduleForm, setScheduleForm] = useState({
    enabled: true,
    weekday: 0,
    time: '08:00',
    timezone: 'Europe/Rome'
  })
  const [scheduleDirty, setScheduleDirty] = useState(false)
  const [operation, setOperation] = useState({ pending: false, message: '', error: false })

  useEffect(() => {
    if (!weeklySchedule.data || scheduleDirty) return
    setScheduleForm({
      enabled: weeklySchedule.data.enabled,
      weekday: weeklySchedule.data.weekday,
      time: weeklySchedule.data.time,
      timezone: weeklySchedule.data.timezone
    })
  }, [weeklySchedule.data, scheduleDirty])

  if (!adminEnabled) {
    return (
      <div className="page-stack">
        <PageHeader eyebrow="Accesso negato" title="Area amministrativa">
          Il tuo account non dispone dei privilegi necessari.
        </PageHeader>
      </div>
    )
  }

  const reloadAll = () => {
    players.reload()
    ips.reload()
    info.reload()
    commands.reload()
    guilds.reload()
    weeklySchedule.reload()
  }
  const mutate = async (description: string, action: () => Promise<unknown>) => {
    if (!window.confirm(`Confermi: ${description}?`)) return false
    setOperation({ pending: true, message: 'Comando in corso...', error: false })
    try {
      await action()
      setOperation({ pending: false, message: 'Comando completato.', error: false })
      commands.reload()
      return true
    } catch (cause) {
      setOperation({
        pending: false,
        message: cause instanceof Error ? cause.message : 'Comando non riuscito.',
        error: true
      })
      return false
    }
  }
  const announce = async (event: FormEvent) => {
    event.preventDefault()
    if (await mutate(`inviare l'annuncio “${message}”`, () => api.announce(message))) setMessage('')
  }
  const unban = async (event: FormEvent) => {
    event.preventDefault()
    if (await mutate(`revocare il ban per ${unbanId}`, () => api.playerCommand('unban', unbanId))) setUnbanId('')
  }
  const saveSchedule = async (event: FormEvent) => {
    event.preventDefault()
    if (
      await mutate('salvare la pianificazione del report settimanale', () =>
        api.updateWeeklyReportSchedule(scheduleForm)
      )
    ) {
      setScheduleDirty(false)
      weeklySchedule.reload()
    }
  }

  const scheduleStatus = {
    never: 'Mai eseguito',
    running: 'Invio in corso',
    success: 'Completato',
    failed: 'Non riuscito',
    interrupted: 'Interrotto'
  }

  return (
    <div className="page-stack admin-page">
      <PageHeader eyebrow="Pannello di amministrazione" title="Admin">
        Snapshot riservati, diagnostica e comandi inoltrati alle REST API Palworld.
      </PageHeader>
      <div className="admin-toolbar">
        <p className={operation.error ? 'error-text' : ''} role="status" aria-live="polite">
          {operation.message || 'Canale comandi pronto.'}
        </p>
        <button type="button" onClick={reloadAll}>
          <IconRefresh aria-hidden="true" /> Aggiorna tutto
        </button>
      </div>
      <Panel title="Avvisi del mondo" eyebrow="Controlli automatici">
        <DataState loading={guilds.loading} error={guilds.error} onRetry={guilds.reload} hasData={Boolean(guilds.data)}>
          <div className="admin-alert-grid">
            {(guilds.data?.alerts || []).map((alert) => (
              <article key={`${alert.title}-${alert.detail}`} data-level={alert.level}>
                <IconAlertTriangle aria-hidden="true" />
                <strong>{alert.title}</strong>
                <span>{alert.detail}</span>
              </article>
            ))}
            {!guilds.data?.alerts?.length ? (
              <article data-level="ok">
                <IconShieldLock aria-hidden="true" />
                <strong>Nessuna anomalia rilevata</strong>
                <span>Gilde, basi e sincronizzazione risultano regolari.</span>
              </article>
            ) : null}
          </div>
          <p className="data-caption">
            Snapshot avvisi aggiornato: {date(guilds.data?.updated_at)}
            {guilds.data?.stale ? ' · in ritardo' : ''}
          </p>
        </DataState>
      </Panel>
      <Panel title="Report settimanale" eyebrow="Pianificazione automatica">
        <p className="section-hint">
          Lo scheduler è eseguito nel container del sito. La finestra del report termina all'orario pianificato nel fuso
          configurato, anche dopo un riavvio.
        </p>
        <DataState
          loading={weeklySchedule.loading}
          error={weeklySchedule.error}
          onRetry={weeklySchedule.reload}
          hasData={Boolean(weeklySchedule.data)}
        >
          <form className="schedule-form" onSubmit={saveSchedule}>
            <label className="schedule-toggle">
              <input
                type="checkbox"
                checked={scheduleForm.enabled}
                onChange={(event) => {
                  setScheduleDirty(true)
                  setScheduleForm({ ...scheduleForm, enabled: event.target.checked })
                }}
              />
              Invio automatico attivo
            </label>
            <label>
              Giorno
              <select
                value={scheduleForm.weekday}
                disabled={!scheduleForm.enabled}
                onChange={(event) => {
                  setScheduleDirty(true)
                  setScheduleForm({ ...scheduleForm, weekday: Number(event.target.value) })
                }}
              >
                {['Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato', 'Domenica'].map((label, index) => (
                  <option key={label} value={index}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Ora
              <input
                type="time"
                required
                value={scheduleForm.time}
                disabled={!scheduleForm.enabled}
                onChange={(event) => {
                  setScheduleDirty(true)
                  setScheduleForm({ ...scheduleForm, time: event.target.value })
                }}
              />
            </label>
            <label>
              Fuso orario
              <input
                required
                maxLength={64}
                value={scheduleForm.timezone}
                disabled={!scheduleForm.enabled}
                onChange={(event) => {
                  setScheduleDirty(true)
                  setScheduleForm({ ...scheduleForm, timezone: event.target.value })
                }}
              />
            </label>
            <button type="submit" disabled={operation.pending}>
              <IconCalendarTime aria-hidden="true" /> Salva pianificazione
            </button>
          </form>
          <dl className="stat-list horizontal schedule-status">
            <div>
              <dt>Stato</dt>
              <dd>{scheduleStatus[weeklySchedule.data?.last_run.status || 'never']}</dd>
            </div>
            <div>
              <dt>Prossimo invio</dt>
              <dd>
                {weeklySchedule.data?.enabled
                  ? date(weeklySchedule.data.next_run_at, false, weeklySchedule.data.timezone)
                  : 'Disattivato'}
              </dd>
            </div>
            <div>
              <dt>Ultimo avvio</dt>
              <dd>{date(weeklySchedule.data?.last_run.started_at, false, weeklySchedule.data?.timezone)}</dd>
            </div>
            <div>
              <dt>Esito tecnico</dt>
              <dd>{weeklySchedule.data?.last_run.error || 'Nessun errore'}</dd>
            </div>
          </dl>
        </DataState>
      </Panel>
      <Panel title="Snapshot Palworld" eyebrow="Ultimo elenco ricevuto">
        <DataState
          loading={players.loading}
          error={players.error}
          onRetry={players.reload}
          hasData={Boolean(players.data)}
        >
          {!players.data?.available ? (
            <p className="data-notice warning">Nessuno snapshot giocatori ancora disponibile.</p>
          ) : null}
          {players.data?.stale ? (
            <p className="data-notice warning">
              Elenco in ritardo: non rappresenta necessariamente lo stato online corrente.
            </p>
          ) : null}
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Giocatore</th>
                  <th>Livello</th>
                  <th>Ping</th>
                  <th>Coordinate</th>
                </tr>
              </thead>
              <tbody>
                {(players.data?.players || []).map((player) => (
                  <tr key={player.id}>
                    <td>
                      <strong>{player.name}</strong>
                    </td>
                    <td>{number(player.level)}</td>
                    <td>{number(player.ping, 1)} ms</td>
                    <td>
                      <code>
                        X {number(player.location_x)} / Y {number(player.location_y)}
                      </code>
                    </td>
                  </tr>
                ))}
                {!players.data?.players.length ? (
                  <tr>
                    <td colSpan={4} className="empty-row">
                      Nessun giocatore online.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <p className="data-caption">
            {players.data?.stale ? 'Ultimo snapshot' : 'Online'} · {date(players.data?.generated_at)}
          </p>
        </DataState>
      </Panel>
      <Panel title="IP giocatori memorizzati" eyebrow="Dati riservati">
        <p className="section-hint">
          L'ultimo IP osservato è visibile esclusivamente agli amministratori per sicurezza e moderazione e non compare
          nelle API membri.
        </p>
        <DataState loading={ips.loading} error={ips.error} onRetry={ips.reload} hasData={Boolean(ips.data)}>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Giocatore</th>
                  <th>IP</th>
                  <th>Osservato</th>
                  <th>Ultimo accesso</th>
                  <th>Stato</th>
                </tr>
              </thead>
              <tbody>
                {(ips.data?.players || []).map((player) => (
                  <tr key={`${player.name}-${player.ip}`}>
                    <td>
                      <strong>{player.name}</strong>
                      <small>{player.account_name}</small>
                    </td>
                    <td>
                      <code>{player.ip}</code>
                    </td>
                    <td>{date(player.observed_at)}</td>
                    <td>{date(player.last_seen)}</td>
                    <td>
                      <StatusBadge online={player.online} />
                    </td>
                  </tr>
                ))}
                {!ips.data?.players.length ? (
                  <tr>
                    <td colSpan={5} className="empty-row">
                      Nessun IP memorizzato.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </DataState>
      </Panel>
      <Panel title="Stato Palworld" eyebrow="Informazioni server">
        <DataState loading={info.loading} error={info.error} onRetry={info.reload} hasData={Boolean(info.data)}>
          {!info.data?.available ? (
            <p className="data-notice warning">Snapshot informazioni Palworld non ancora disponibile.</p>
          ) : null}
          {info.data?.stale ? <p className="data-notice warning">Le informazioni server sono in ritardo.</p> : null}
          <dl className="stat-list horizontal">
            <div>
              <dt>Server</dt>
              <dd>{String(info.data?.servername || '--')}</dd>
            </div>
            <div>
              <dt>Versione</dt>
              <dd>{String(info.data?.version || '--')}</dd>
            </div>
            <div>
              <dt>Descrizione</dt>
              <dd>{String(info.data?.description || '--')}</dd>
            </div>
            <div>
              <dt>Snapshot</dt>
              <dd>{date(info.data?.generated_at)}</dd>
            </div>
            <div>
              <dt>Freschezza</dt>
              <dd>{info.data?.stale ? 'In ritardo' : 'Regolare'}</dd>
            </div>
          </dl>
        </DataState>
      </Panel>
      <Panel title="Comandi server" eyebrow="Azioni registrate">
        <p className="section-hint">
          Le azioni sono inoltrate direttamente alle REST API Palworld e registrate nel log di audit. I UserID raw sono
          mostrati solo in questo pannello e non vengono persistiti.
        </p>
        <form className="command-form" onSubmit={announce}>
          <label>
            Annuncio in chat
            <textarea
              maxLength={500}
              required
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="Messaggio broadcast (max 500 caratteri)"
            />
          </label>
          <button type="submit" disabled={operation.pending}>
            <IconSend aria-hidden="true" /> Invia annuncio
          </button>
        </form>
        <DataState
          loading={commands.loading}
          error={commands.error}
          onRetry={commands.reload}
          hasData={Boolean(commands.data)}
        >
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Giocatore / UserID</th>
                  <th>Livello</th>
                  <th>Ping</th>
                  <th>Coordinate</th>
                  <th>Azioni</th>
                </tr>
              </thead>
              <tbody>
                {(commands.data?.players || []).map((player) => (
                  <tr key={player.userId}>
                    <td>
                      <strong>{player.name || '?'}</strong>
                      <code>{player.userId}</code>
                    </td>
                    <td>{number(player.level)}</td>
                    <td>{number(player.ping, 1)} ms</td>
                    <td>
                      X {number(player.location_x)} / Y {number(player.location_y)}
                    </td>
                    <td className="table-actions">
                      <button
                        type="button"
                        disabled={operation.pending}
                        onClick={() =>
                          mutate(`espellere ${player.name} (${player.userId})`, () =>
                            api.playerCommand('kick', player.userId)
                          )
                        }
                      >
                        Kick
                      </button>
                      <button
                        type="button"
                        className="danger"
                        disabled={operation.pending}
                        onClick={() =>
                          mutate(`bannare ${player.name} (${player.userId})`, () =>
                            api.playerCommand('ban', player.userId)
                          )
                        }
                      >
                        Ban
                      </button>
                    </td>
                  </tr>
                ))}
                {!commands.data?.players.length ? (
                  <tr>
                    <td colSpan={5} className="empty-row">
                      Nessun giocatore online disponibile per i comandi.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </DataState>
        <form className="command-form inline" onSubmit={unban}>
          <label>
            Revoca ban
            <input
              required
              maxLength={64}
              value={unbanId}
              onChange={(event) => setUnbanId(event.target.value)}
              placeholder="UserID del giocatore"
            />
          </label>
          <button type="submit" disabled={operation.pending}>
            Revoca ban
          </button>
        </form>
      </Panel>
    </div>
  )
}
