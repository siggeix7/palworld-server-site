import { api } from '../../api/resources'
import { useApiResource } from '../../api/useApiResource'
import { date, number } from '../../shared/format'
import { DataState, PageHeader, Panel } from '../../shared/ui'

export function GuildsPage() {
  const guilds = useApiResource((signal) => api.guilds(signal), { key: 'guilds', intervalMs: 120_000 })

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Rete delle gilde" title="Gilde">
        Basi, membri e condizioni operative estratte dall'ultimo salvataggio del mondo.
      </PageHeader>
      <DataState loading={guilds.loading} error={guilds.error} onRetry={guilds.reload} hasData={Boolean(guilds.data)}>
        {guilds.data ? (
          <>
            {guilds.data.stale ? (
              <p className="data-notice warning" role="status">
                Lo snapshot del mondo è in ritardo.
              </p>
            ) : null}
            <p className="data-caption">Snapshot aggiornato: {date(guilds.data.updated_at)}</p>
            <div className="guild-grid">
              {guilds.data.guilds.map((guild) => {
                const bases = guilds.data?.bases.filter((base) => base.group_id === guild.group_id) || []
                return (
                  <Panel
                    key={guild.group_id}
                    title={guild.guild_name || 'Gilda senza nome'}
                    eyebrow={`${number(guild.players.length)} membri · ${number(guild.base_count ?? bases.length)} basi`}
                    className="guild-card"
                  >
                    <div className="guild-metrics">
                      <div>
                        <strong>{number(guild.pal_count ?? 0)}</strong>
                        <span>Pal registrati</span>
                      </div>
                      <div>
                        <strong>{number(guild.worker_count ?? 0)}</strong>
                        <span>Lavoratori</span>
                      </div>
                      <div>
                        <strong>{number(guild.working_count ?? 0)}</strong>
                        <span>Al lavoro</span>
                      </div>
                      <div data-warning={Number(guild.problem_worker_count) > 0}>
                        <strong>{number(guild.problem_worker_count ?? 0)}</strong>
                        <span>Da controllare</span>
                      </div>
                    </div>
                    {bases.length ? (
                      <div className="base-list">
                        {bases.map((base) => (
                          <article key={base.base_id}>
                            <strong>{base.name || 'Base senza nome'}</strong>
                            <span>
                              {number(base.worker_count ?? 0)} assegnati · {number(base.working_count ?? 0)} al lavoro
                            </span>
                            <small
                              data-state={
                                base.raid_active ? 'danger' : Number(base.problem_worker_count) ? 'warning' : 'ok'
                              }
                            >
                              {base.raid_active
                                ? 'Invasione attiva'
                                : Number(base.problem_worker_count)
                                  ? `${number(base.problem_worker_count)} da controllare`
                                  : 'Nessuna criticità'}
                            </small>
                          </article>
                        ))}
                      </div>
                    ) : null}
                    {guild.players.length ? (
                      <details className="details-block">
                        <summary>Membri ({number(guild.players.length)})</summary>
                        <dl>
                          {guild.players.map((player) => (
                            <div key={player.player_name}>
                              <dt>{player.player_name}</dt>
                              <dd>{player.is_admin ? 'Capo gilda' : 'Membro'}</dd>
                            </div>
                          ))}
                        </dl>
                      </details>
                    ) : null}
                  </Panel>
                )
              })}
              {!guilds.data.guilds.length ? <p className="data-state">Nessuna gilda disponibile.</p> : null}
            </div>
          </>
        ) : null}
      </DataState>
    </div>
  )
}
