import { IconSearch } from '@tabler/icons-react'
import { useState } from 'react'
import { api } from '../../api/resources'
import { useApiResource } from '../../api/useApiResource'
import { useServerSnapshot } from '../../app/server'
import { date, number, setting, settingLabel } from '../../shared/format'
import { DataState, MetricGrid, PageHeader, Panel, StatusBadge } from '../../shared/ui'

const settingGroups = [
  [
    'Progressione',
    ['Difficulty', 'ExpRate', 'PalCaptureRate', 'PalSpawnNumRate', 'WorkSpeedRate', 'PalEggDefaultHatchingTime']
  ],
  [
    'Tempo e risorse',
    [
      'DayTimeSpeedRate',
      'NightTimeSpeedRate',
      'CollectionDropRate',
      'CollectionObjectHpRate',
      'CollectionObjectRespawnSpeedRate',
      'EnemyDropItemRate',
      'DropItemMaxNum',
      'DropItemAliveMaxHours'
    ]
  ],
  [
    'Giocatori',
    [
      'PlayerDamageRateAttack',
      'PlayerDamageRateDefense',
      'PlayerStomachDecreaceRate',
      'PlayerStaminaDecreaceRate',
      'PlayerAutoHPRegeneRate',
      'PlayerAutoHpRegeneRateInSleep',
      'DeathPenalty',
      'bEnableFriendlyFire'
    ]
  ],
  [
    'Pal',
    [
      'PalDamageRateAttack',
      'PalDamageRateDefense',
      'PalStomachDecreaceRate',
      'PalStaminaDecreaceRate',
      'PalAutoHPRegeneRate',
      'PalAutoHpRegeneRateInSleep'
    ]
  ],
  [
    'Basi e gilde',
    [
      'BaseCampMaxNum',
      'BaseCampWorkerMaxNum',
      'GuildPlayerMaxNum',
      'BuildObjectDamageRate',
      'BuildObjectDeteriorationDamageRate',
      'bAutoResetGuildNoOnlinePlayers',
      'AutoResetGuildTimeNoOnlinePlayers',
      'bCanPickupOtherGuildDeathPenaltyDrop',
      'bEnableDefenseOtherGuildPlayer'
    ]
  ],
  [
    'Multiplayer',
    [
      'ServerPlayerMaxNum',
      'CoopPlayerMaxNum',
      'bIsPvP',
      'bEnablePlayerToPlayerDamage',
      'bEnableFastTravel',
      'bEnableNonLoginPenalty',
      'CrossplayPlatforms',
      'AllowConnectPlatform'
    ]
  ],
  [
    'Mondo e salvataggi',
    ['bEnableInvaderEnemy', 'bIsStartLocationSelectByMap', 'bExistPlayerAfterLogout', 'bIsUseBackupSaveData']
  ],
  ['Identità server', ['ServerName', 'ServerDescription']]
] as const

export function WorldPage() {
  const [query, setQuery] = useState('')
  const snapshot = useServerSnapshot()
  const diff = useApiResource((signal) => api.worldDiff(signal), { key: 'world-diff', intervalMs: 120_000 })
  const save = useApiResource((signal) => api.guilds(signal), { key: 'world-save', intervalMs: 300_000 })
  const settings = snapshot.data?.settings || {}
  const normalized = query.trim().toLocaleLowerCase('it')
  const matches = (key: string) =>
    Object.hasOwn(settings, key) &&
    (!normalized || `${settingLabel(key)} ${setting(settings[key])}`.toLocaleLowerCase('it').includes(normalized))
  const world = save.data?.world || {}
  const groupedKeys = new Set<string>(settingGroups.flatMap(([, keys]) => keys))
  const groups = [
    ...settingGroups,
    ['Altre impostazioni', Object.keys(settings).filter((key) => !groupedKeys.has(key))]
  ] as ReadonlyArray<readonly [string, readonly string[]]>

  return (
    <div className="page-stack">
      <PageHeader eyebrow="Configurazione mondo" title="Mondo">
        Profilo operativo, regole pubbliche, stato del salvataggio e scostamenti dai valori vanilla.
      </PageHeader>
      <Panel title="Mondo attuale" eyebrow="Stato dal salvataggio">
        <DataState loading={save.loading} error={save.error} onRetry={save.reload} hasData={Boolean(save.data)}>
          <MetricGrid
            items={[
              {
                label: 'Giorno mondo',
                value: number(snapshot.data?.metrics.days),
                detail: 'tempo di gioco',
                tone: 'cyan'
              },
              {
                label: 'Invasioni attive',
                value: number(world.active_raid_count ?? 0),
                detail: 'basi sotto attacco',
                tone: Number(world.active_raid_count) ? 'danger' : 'green'
              },
              {
                label: 'Allarmi piattaforme',
                value: number(world.oil_rig_alert_count ?? 0),
                detail: 'oil rig in allerta'
              },
              {
                label: 'Piattaforme completate',
                value: `${number(world.oil_rig_cleared_count ?? 0)} / ${number(world.oil_rig_count ?? 0)}`,
                detail: 'stato salvato'
              }
            ]}
          />
          <p className="data-caption">
            Snapshot aggiornato: {date(save.data?.updated_at)}
            {save.data?.stale ? ' · dati in ritardo' : ''}
          </p>
        </DataState>
      </Panel>
      <Panel
        title="Regole del mondo"
        eyebrow="Configurazione pubblica"
        action={
          <label className="search-field">
            <IconSearch aria-hidden="true" />
            <span className="sr-only">Cerca impostazione</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Cerca una regola"
            />
          </label>
        }
      >
        <DataState
          loading={snapshot.loading}
          error={snapshot.error}
          onRetry={snapshot.reload}
          hasData={Boolean(snapshot.data)}
        >
          {snapshot.data ? (
            <>
              <aside className="server-profile">
                <div>
                  <p className="eyebrow">Identikit operativo</p>
                  <h3>Scheda server</h3>
                  <StatusBadge online={snapshot.data.status.online} stale={snapshot.data.status.stale} />
                </div>
                <dl className="stat-list horizontal">
                  <div>
                    <dt>Giocatori</dt>
                    <dd>
                      {number(snapshot.data.metrics.currentplayernum)} / {number(snapshot.data.metrics.maxplayernum)}
                    </dd>
                  </div>
                  <div>
                    <dt>Stato</dt>
                    <dd>{snapshot.data.status.online ? 'Online' : 'Offline'}</dd>
                  </div>
                  <div>
                    <dt>Avviato</dt>
                    <dd>
                      <time dateTime={snapshot.data.status.started_at || undefined}>
                        {date(snapshot.data.status.started_at)}
                      </time>
                    </dd>
                  </div>
                  <div>
                    <dt>Piattaforme</dt>
                    <dd>{setting(settings.CrossplayPlatforms ?? settings.AllowConnectPlatform)}</dd>
                  </div>
                  <div>
                    <dt>Versione</dt>
                    <dd>{snapshot.data.info.version || '--'}</dd>
                  </div>
                  <div>
                    <dt>Modalità</dt>
                    <dd>{Object.hasOwn(settings, 'bIsPvP') ? (settings.bIsPvP ? 'PvP' : 'PvE') : '--'}</dd>
                  </div>
                  <div>
                    <dt>Backup salvataggi</dt>
                    <dd>
                      {Object.hasOwn(settings, 'bIsUseBackupSaveData') ? setting(settings.bIsUseBackupSaveData) : '--'}
                    </dd>
                  </div>
                  <div>
                    <dt>Invasori</dt>
                    <dd>
                      {Object.hasOwn(settings, 'bEnableInvaderEnemy') ? setting(settings.bEnableInvaderEnemy) : '--'}
                    </dd>
                  </div>
                </dl>
              </aside>
              <section className="world-highlights" aria-label="Regole principali del mondo">
                <article>
                  <span>Modalità</span>
                  <strong>{Object.hasOwn(settings, 'bIsPvP') ? (settings.bIsPvP ? 'PvP' : 'PvE') : '--'}</strong>
                </article>
                <article>
                  <span>Esperienza</span>
                  <strong>{Object.hasOwn(settings, 'ExpRate') ? `× ${number(settings.ExpRate, 2)}` : '--'}</strong>
                </article>
                <article>
                  <span>Raccolta</span>
                  <strong>
                    {Object.hasOwn(settings, 'CollectionDropRate')
                      ? `× ${number(settings.CollectionDropRate, 2)}`
                      : '--'}
                  </strong>
                </article>
                <article>
                  <span>Viaggio rapido</span>
                  <strong>
                    {Object.hasOwn(settings, 'bEnableFastTravel') ? setting(settings.bEnableFastTravel) : '--'}
                  </strong>
                </article>
                <article>
                  <span>Capacità</span>
                  <strong>{number(settings.ServerPlayerMaxNum ?? snapshot.data.metrics.maxplayernum)} giocatori</strong>
                </article>
              </section>
              <div className="settings-grid">
                {groups.map(([title, keys]) => {
                  const visible = keys.filter(matches)
                  if (!visible.length) return null
                  return (
                    <article className="settings-group" key={title}>
                      <h3>{title}</h3>
                      {visible.map((key) => (
                        <div className="setting-row" key={key}>
                          <span>{settingLabel(key)}</span>
                          <strong>{setting(settings[key])}</strong>
                          <code>{key}</code>
                        </div>
                      ))}
                    </article>
                  )
                })}
                {!groups.some(([, keys]) => keys.some(matches)) ? (
                  <p className="empty-row">Nessuna regola corrisponde alla ricerca.</p>
                ) : null}
              </div>
            </>
          ) : null}
        </DataState>
      </Panel>
      <Panel title="Differenze vanilla" eyebrow="Scostamenti attivi">
        <DataState loading={diff.loading} error={diff.error} onRetry={diff.reload} hasData={Boolean(diff.data)}>
          {diff.data ? (
            <div className="diff-list">
              {diff.data.diffs.map((item) => (
                <article key={item.key}>
                  <div>
                    <strong>{settingLabel(item.key)}</strong>
                    <code>{item.key}</code>
                  </div>
                  <span>{setting(item.current)}</span>
                  <small>vanilla {setting(item.vanilla)}</small>
                </article>
              ))}
              {!diff.data.has_settings ? <p className="empty-row">Configurazione non ancora ricevuta.</p> : null}
              {diff.data.has_settings && !diff.data.total ? (
                <p className="empty-row">Nessuna differenza rispetto ai valori vanilla.</p>
              ) : null}
            </div>
          ) : null}
        </DataState>
      </Panel>
    </div>
  )
}
