import { IconSearch, IconStar, IconStarFilled } from '@tabler/icons-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { ArchivePlayer, Snapshot } from '../../api/contracts'
import { api } from '../../api/resources'
import { useApiResource } from '../../api/useApiResource'
import { useServerSnapshot } from '../../app/server'
import { date, minutes, number } from '../../shared/format'
import { readStorage, writeStorage } from '../../shared/storage'
import { DataState, PageHeader, Panel, StatusBadge } from '../../shared/ui'

const statusPointLabels: Record<string, string> = {
  max_hp: 'HP massimo',
  stamina: 'Stamina',
  attack: 'Attacco',
  carry_weight: 'Peso trasportabile',
  capture_rate: 'Cattura',
  work_speed: 'Velocità lavoro'
}

function initialFavorites() {
  try {
    const stored = JSON.parse(readStorage('observatory.favoritePlayers') || '[]')
    return new Set<string>(Array.isArray(stored) ? stored.filter((value) => typeof value === 'string') : [])
  } catch {
    return new Set<string>()
  }
}

export function PlayersPage() {
  const snapshot = useServerSnapshot()
  const archive = useApiResource((signal) => api.players(signal), { key: 'players-archive', intervalMs: 60_000 })
  const [query, setQuery] = useState('')
  const [favoritesOnly, setFavoritesOnly] = useState(false)
  const [favorites, setFavorites] = useState(initialFavorites)
  const players = archive.data?.players || []
  const normalized = query.trim().toLocaleLowerCase('it')
  const visible = players
    .filter((player) => !favoritesOnly || favorites.has(player.id))
    .filter(
      (player) => !normalized || `${player.name} ${player.accountName}`.toLocaleLowerCase('it').includes(normalized)
    )
    .sort(
      (left, right) =>
        Number(favorites.has(right.id)) - Number(favorites.has(left.id)) || left.name.localeCompare(right.name, 'it')
    )
  const online = snapshot.data?.players || []

  const toggleFavorite = (id: string) => {
    setFavorites((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      writeStorage('observatory.favoritePlayers', JSON.stringify([...next]))
      return next
    })
  }

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Manifesto esploratori" title="Giocatori">
        Presenze in tempo reale, progressione dal salvataggio e archivio delle sessioni.
      </PageHeader>
      <Panel title="Giocatori online" eyebrow="Telemetria corrente">
        <DataState
          loading={snapshot.loading}
          error={snapshot.error}
          onRetry={snapshot.reload}
          hasData={Boolean(snapshot.data)}
        >
          <LiveRoster
            players={online}
            stale={Boolean(snapshot.data?.status.players_stale || snapshot.data?.status.stale)}
          />
        </DataState>
      </Panel>
      <Panel
        title="Tutti i giocatori"
        eyebrow="Archivio presenze"
        action={
          <div className="archive-filters">
            <label className="search-field">
              <IconSearch />
              <span className="sr-only">Cerca giocatore</span>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Nome o account"
              />
            </label>
            <label className="check-field">
              <input
                type="checkbox"
                checked={favoritesOnly}
                onChange={(event) => setFavoritesOnly(event.target.checked)}
              />{' '}
              Solo preferiti
            </label>
          </div>
        }
      >
        <DataState
          loading={archive.loading}
          error={archive.error}
          onRetry={archive.reload}
          hasData={Boolean(archive.data)}
        >
          <p className="data-caption" role="status">
            {number(visible.length)} di {number(players.length)} giocatori · aggiornato{' '}
            {date(archive.data?.generated_at)}
          </p>
          <div className="player-archive-grid">
            {visible.map((player) => (
              <PlayerCard
                key={player.id}
                player={player}
                favorite={favorites.has(player.id)}
                onFavorite={() => toggleFavorite(player.id)}
              />
            ))}
            {!visible.length ? <p className="empty-row">Nessun giocatore corrisponde ai filtri.</p> : null}
          </div>
        </DataState>
      </Panel>
    </div>
  )
}

type LivePlayer = Snapshot['players'][number]

function LiveRoster({ players, stale }: { players: LivePlayer[]; stale: boolean }) {
  return (
    <>
      {stale ? (
        <p className="data-notice warning">Il roster live è obsoleto; le righe sono l'ultimo dato valido.</p>
      ) : null}
      <div className="table-scroll desktop-live-roster">
        <table className="data-table live-roster-table">
          <thead>
            <tr>
              <th>Giocatore</th>
              <th>Livello</th>
              <th>Ping</th>
              <th>Costruzioni</th>
              <th>Sessione</th>
              <th>Coordinate</th>
              <th>Stato</th>
            </tr>
          </thead>
          <tbody>
            {players.map((player) => (
              <tr key={player.id}>
                <td>
                  <Link to={`/giocatori/${encodeURIComponent(player.id)}/`}>
                    <strong>{player.name}</strong>
                    <small>{player.accountName || 'account non disponibile'}</small>
                  </Link>
                </td>
                <td>{number(player.level)}</td>
                <td>{number(player.ping)} ms</td>
                <td>{number(player.building_count)}</td>
                <td>
                  <strong>{durationLabel(player.session?.current_session)}</strong>
                  <small>{durationLabel(player.session?.online_7d)} negli ultimi 7g</small>
                </td>
                <td>
                  <code>{locationLabel(player)}</code>
                </td>
                <td>
                  <StatusBadge online={!stale} stale={stale} />
                </td>
              </tr>
            ))}
            {!players.length ? (
              <tr>
                <td colSpan={7} className="empty-row">
                  Nessun giocatore online.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <div className="mobile-live-roster">
        {players.map((player) => (
          <article className="online-player" key={player.id}>
            <span className="player-avatar">{player.name.slice(0, 2).toUpperCase()}</span>
            <div>
              <Link to={`/giocatori/${encodeURIComponent(player.id)}/`}>{player.name}</Link>
              <small>{player.accountName || 'account non disponibile'}</small>
            </div>
            <StatusBadge online={!stale} stale={stale} />
            <dl>
              <div>
                <dt>Livello</dt>
                <dd>{number(player.level)}</dd>
              </div>
              <div>
                <dt>Ping</dt>
                <dd>{number(player.ping)} ms</dd>
              </div>
              <div>
                <dt>Costruzioni</dt>
                <dd>{number(player.building_count)}</dd>
              </div>
              <div>
                <dt>Sessione</dt>
                <dd>{durationLabel(player.session?.current_session)}</dd>
              </div>
              <div>
                <dt>Online 7g</dt>
                <dd>{durationLabel(player.session?.online_7d)}</dd>
              </div>
              <div>
                <dt>Coordinate</dt>
                <dd>{locationLabel(player)}</dd>
              </div>
            </dl>
          </article>
        ))}
        {!players.length ? <p className="empty-row">Nessun giocatore online.</p> : null}
      </div>
    </>
  )
}

function durationLabel(seconds: number | null | undefined) {
  return seconds == null ? '--' : minutes(seconds / 60)
}

function locationLabel(player: LivePlayer) {
  return player.location_available === false || player.location_x == null || player.location_y == null
    ? 'Posizione non disponibile'
    : `X ${number(player.location_x)} · Y ${number(player.location_y)}`
}

function PlayerCard({
  player,
  favorite,
  onFavorite
}: {
  player: ArchivePlayer
  favorite: boolean
  onFavorite: () => void
}) {
  const stats = Object.entries(player.status_points).filter(([, value]) => value > 0)
  const ping = player.ping_7d?.sample_count
    ? `${number(player.ping_7d.average)} ms · ${number(player.ping_7d.minimum)}–${number(player.ping_7d.maximum)} ms`
    : '--'
  return (
    <article className="player-card">
      <header>
        <span className="player-avatar">{player.name.slice(0, 2).toUpperCase()}</span>
        <div>
          <strong>{player.name}</strong>
          <small>
            {player.save_only ? 'Personaggio storico dal salvataggio' : player.accountName || 'account non disponibile'}
          </small>
        </div>
        <StatusBadge online={player.online} />
        <button
          type="button"
          className="favorite-button"
          aria-pressed={favorite}
          aria-label={`${favorite ? 'Rimuovi' : 'Aggiungi'} ${player.name} dai preferiti locali`}
          onClick={onFavorite}
        >
          {favorite ? <IconStarFilled /> : <IconStar />}
        </button>
      </header>
      <dl className="stat-list">
        <div>
          <dt>Livello</dt>
          <dd>Lv. {number(player.level)}</dd>
        </div>
        <div>
          <dt>Esperienza</dt>
          <dd>{player.save_available ? number(player.exp) : '--'}</dd>
        </div>
        <div>
          <dt>Pal posseduti</dt>
          <dd>{player.save_available ? number(player.owned_pal_count) : '--'}</dd>
        </div>
        <div>
          <dt>Gilda</dt>
          <dd>
            {player.guild_name || '--'}
            {player.is_guild_admin ? ' · capogilda' : ''}
          </dd>
        </div>
        <div>
          <dt>Costruzioni</dt>
          <dd>{player.save_only ? '--' : number(player.building_count)}</dd>
        </div>
        <div>
          <dt>Ping medio/min/max 7g</dt>
          <dd>{ping}</dd>
        </div>
        <div>
          <dt>Ultimi 30g</dt>
          <dd>{minutes(player.minutes_30d)}</dd>
        </div>
        <div>
          <dt>Ultimi 365g</dt>
          <dd>{minutes(player.minutes_365d)}</dd>
        </div>
        <div>
          <dt>Da sempre</dt>
          <dd>{minutes(player.minutes_all)}</dd>
        </div>
        <div>
          <dt>Sessioni</dt>
          <dd>{number(player.session_count)}</dd>
        </div>
        <div>
          <dt>Media sessione</dt>
          <dd>{minutes(player.average_session_minutes)}</dd>
        </div>
        <div>
          <dt>Sessione più lunga</dt>
          <dd>{minutes(player.longest_session_minutes)}</dd>
        </div>
        <div>
          <dt>Giorni attivi 30g</dt>
          <dd>{number(player.active_days_30d)}</dd>
        </div>
        <div>
          <dt>Prima visita</dt>
          <dd>{date(player.first_seen)}</dd>
        </div>
        <div>
          <dt>Ultimo accesso</dt>
          <dd>{date(player.last_seen)}</dd>
        </div>
        <div>
          <dt>Punti inutilizzati</dt>
          <dd>{player.save_available ? number(player.unused_status_points) : '--'}</dd>
        </div>
      </dl>
      {!player.save_only ? (
        <Link className="text-link" to={`/giocatori/${encodeURIComponent(player.id)}/`}>
          Apri profilo completo ↘
        </Link>
      ) : null}
      {stats.length ? (
        <details className="details-block">
          <summary>Punti statistiche personaggio</summary>
          <dl>
            {stats.map(([key, value]) => (
              <div key={key}>
                <dt>{statusPointLabels[key] || key}</dt>
                <dd>{number(value)}</dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}
      {player.periods.length ? (
        <details className="details-block">
          <summary>Periodi online ({number(player.periods.length)})</summary>
          <ol className="session-list archive-periods">
            {player.periods.map((period) => (
              <li key={period.started_at}>
                <span>
                  <time dateTime={period.started_at}>{date(period.started_at)}</time>
                  {period.active ? (
                    ' · in corso'
                  ) : (
                    <>
                      {' '}
                      → <time dateTime={period.ended_at || undefined}>{date(period.ended_at)}</time>
                    </>
                  )}
                </span>
                <strong>{minutes(period.duration_minutes)}</strong>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </article>
  )
}
