(() => {
  'use strict'

  // Palette and interaction concepts adapted from RNZ01/palworld-server-dashboard.
  // This implementation uses deterministic public IDs; see THIRD_PARTY_NOTICES.txt.
  const PLAYER_COLORS = [
    '#22c55e', '#06b6d4', '#3b82f6', '#8b5cf6', '#ec4899', '#f43f5e',
    '#f97316', '#eab308', '#14b8a6', '#0ea5e9', '#6366f1', '#d946ef',
  ]
  const THEMES = new Set(['observatory', 'tron', 'ares', 'clu', 'athena', 'aphrodite', 'poseidon'])

  const state = {
    snapshot: null,
    worldSaveData: null,
    historySamples: [],
    historyWindow: null,
    chartPoints: [],
    chartHoverIndex: null,
    requests: {},
    notices: { snapshot: null, history: null },
    snapshotTimer: null,
    worldSaveTimer: null,
    snapshotFailures: 0,
    snapshotGeneration: 0,
    historyTimer: null,
    archiveTimer: null,
    archivePlayers: [],
    archiveUpdated: null,
    favoritePlayers: new Set(),
    playerQuery: '',
    favoritesOnly: false,
    toastTimer: null,
  }

  const $ = (selector) => document.querySelector(selector)
  const elements = {
    headerStatus: $('#headerStatus'),
    serverName: $('#serverName'),
    serverDescription: $('#serverDescription'),
    serverVersion: $('#serverVersion'),
    lastUpdate: $('#lastUpdate'),
    heroPlayers: $('#heroPlayers'),
    heroCapacity: $('#heroCapacity'),
    heroFps: $('#heroFps'),
    heroUptime: $('#heroUptime'),
    heroDay: $('#heroDay'),
    signalBar: $('#signalBar'),
    signalAge: $('#signalAge'),
    metricFpsAverage: $('#metricFpsAverage'),
    metricFpsMinimum: $('#metricFpsMinimum'),
    metricFrameTime: $('#metricFrameTime'),
    metricPeak: $('#metricPeak'),
    metricPlayersAverage: $('#metricPlayersAverage'),
    metricBases: $('#metricBases'),
    themeSelect: $('#themeSelect'),
    playersTable: $('#playersTable'),
    mobilePlayers: $('#mobilePlayers'),
    playerArchive: $('#playerArchive'),
    playerArchiveStatus: $('#playerArchiveStatus'),
    playerSearch: $('#playerSearch'),
    favoritesOnly: $('#favoritesOnly'),
    settingsGrid: $('#settingsGrid'),
    settingsSearch: $('#settingsSearch'),
    serverProfile: $('#serverProfile'),
    worldHighlights: $('#worldHighlights'),
    worldDiff: $('#worldDiff'),
    worldSaveStatus: $('#worldSaveStatus'),
    worldSaveUpdated: $('#worldSaveUpdated'),
    worldSaveNotice: $('#worldSaveNotice'),
    eventList: $('#eventList'),
    eventFilter: $('#eventFilter'),
    eventCounts: $('#eventCounts'),
    historyRange: $('#historyRange'),
    historyChart: $('#historyChart'),
    chartEmpty: $('#chartEmpty'),
    chartSummary: $('#chartSummary'),
    chartTooltip: $('#chartTooltip'),
    performanceHealth: $('#performanceHealth'),
    healthLabel: $('#healthLabel'),
    healthScore: $('#healthScore'),
    healthDetail: $('#healthDetail'),
    telemetryStats: $('#telemetryStats'),
    uptime24h: $('#uptime24h'),
    uptime7d: $('#uptime7d'),
    fpsStability: $('#fpsStability'),
    dataGaps: $('#dataGaps'),
    worldDay: $('#worldDay'),
    onlineNow: $('#onlineNow'),
    onlineAverage: $('#onlineAverage'),
    heroDayHome: $('#heroDayHome'),
    heroFpsHome: $('#heroFpsHome'),
    heroUptimeHome: $('#heroUptimeHome'),
    lastUpdateHome: $('#lastUpdateHome'),
    homeRecentActivity: $('#homeRecentActivity'),
    dataNotice: $('#dataNotice'),
    connectionToast: $('#connectionToast'),
  }

  function setText(element, value) {
    if (!element) return
    const text = String(value)
    if (element.textContent !== text) element.textContent = text
  }

  function formatNumber(value, digits = 0) {
    const number = Number(value)
    if (!Number.isFinite(number)) return '--'
    return number.toLocaleString('it-IT', { maximumFractionDigits: digits })
  }

  function formatDuration(value) {
    if (value === null || value === undefined) return '--'
    let seconds = Math.max(0, Number(value) || 0)
    const days = Math.floor(seconds / 86400)
    seconds %= 86400
    const hours = Math.floor(seconds / 3600)
    seconds %= 3600
    const minutes = Math.floor(seconds / 60)
    if (days) return `${days}g ${hours}h`
    if (hours) return `${hours}h ${minutes}m`
    return `${minutes}m`
  }

  function formatShortDuration(value) {
    const seconds = Math.max(0, Math.round(Number(value) || 0))
    if (seconds < 60) return `${seconds}s`
    if (seconds < 3600) {
      const minutes = Math.floor(seconds / 60)
      const remainder = seconds % 60
      return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`
    }
    return formatDuration(seconds)
  }

  function formatDate(value, includeDate = false) {
    if (!value) return 'mai'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '--'
    const options = includeDate
      ? { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }
      : { hour: '2-digit', minute: '2-digit', second: '2-digit' }
    return new Intl.DateTimeFormat('it-IT', options).format(date)
  }

  function formatFullDate(value) {
    if (!value) return 'in corso'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '--'
    return new Intl.DateTimeFormat('it-IT', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date)
  }

  function formatChartDate(value, compact, timeSpan) {
    if (!compact) return formatDate(value, true)
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '--'
    const options = timeSpan > 36 * 60 * 60 * 1000
      ? { day: '2-digit', month: '2-digit' }
      : { hour: '2-digit', minute: '2-digit' }
    return new Intl.DateTimeFormat('it-IT', options).format(date)
  }

  function initials(name) {
    return String(name || '?').split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase()
  }

  function playerColor(playerId) {
    let hash = 2166136261
    for (const character of String(playerId || '')) {
      hash ^= character.charCodeAt(0)
      hash = Math.imul(hash, 16777619)
    }
    return PLAYER_COLORS[(hash >>> 0) % PLAYER_COLORS.length]
  }

  function contrastColor(hex) {
    const channels = [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255)
      .map((value) => (value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4))
    const luminance = channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722
    return ((luminance + .05) / .05) >= (1.05 / (luminance + .05)) ? '#061719' : '#ffffff'
  }

  function pingClass(value) {
    const ping = Number(value)
    if (ping < 80) return 'ping-good'
    if (ping < 150) return 'ping-warn'
    return 'ping-bad'
  }

  function readStorage(key, fallback = null) {
    try {
      return window.localStorage.getItem(key) ?? fallback
    } catch (_error) {
      return fallback
    }
  }

  function writeStorage(key, value) {
    try {
      window.localStorage.setItem(key, value)
    } catch (_error) {
      // Preferences remain optional when storage is blocked.
    }
  }

  function initializeTheme() {
    const stored = readStorage('observatory.theme', 'observatory')
    const theme = THEMES.has(stored) ? stored : 'observatory'
    document.documentElement.dataset.theme = theme
    elements.themeSelect.value = theme
  }

  function hasMapLocation(player) {
    const x = Number(player?.location_x)
    const y = Number(player?.location_y)
    return player?.location_available !== false && Number.isFinite(x) && Number.isFinite(y) && (x !== 0 || y !== 0)
  }

  async function requestJson(url, key, timeout = 8000) {
    if (state.requests[key]) state.requests[key].abort()
    const controller = new AbortController()
    state.requests[key] = controller
    let timedOut = false
    const timer = window.setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeout)
    try {
      const response = await fetch(url, { cache: 'no-store', signal: controller.signal })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      return await response.json()
    } catch (error) {
      if (timedOut) {
        const timeoutError = new Error('request timeout')
        timeoutError.name = 'TimeoutError'
        throw timeoutError
      }
      throw error
    } finally {
      window.clearTimeout(timer)
      if (state.requests[key] === controller) delete state.requests[key]
    }
  }

  function renderNotice() {
    if (!elements.dataNotice) return
    const notice = state.notices.snapshot || state.notices.history
    elements.dataNotice.hidden = !notice
    elements.dataNotice.classList.toggle('error', Boolean(notice?.error))
    setText(elements.dataNotice, notice?.message || '')
  }

  function setNotice(key, message = null, error = false) {
    state.notices[key] = message ? { message, error } : null
    renderNotice()
  }

  function renderPlayersTable(players) {
    if (!elements.playersTable) return
    const focusedId = document.activeElement?.closest('.player-link')?.dataset?.playerId
    elements.playersTable.replaceChildren()
    if (!players.length) {
      const row = document.createElement('tr')
      const cell = document.createElement('td')
      cell.colSpan = 6
      cell.className = 'empty-cell'
      cell.textContent = 'Nessun giocatore online.'
      row.appendChild(cell)
      elements.playersTable.appendChild(row)
      return
    }

    for (const player of players) {
      const mapped = hasMapLocation(player)
      const row = document.createElement('tr')
      const identity = document.createElement('td')
      const playerButton = document.createElement('a')
      playerButton.className = 'player-link'
      playerButton.dataset.playerId = player.id
      playerButton.href = `/giocatori/${encodeURIComponent(player.id)}/`
      playerButton.style.setProperty('--player-color', playerColor(player.id))
      const name = document.createElement('strong')
      name.textContent = player.name
      const account = document.createElement('small')
      account.textContent = player.accountName || 'account non disponibile'
      playerButton.append(name, account)
      identity.appendChild(playerButton)

      const level = document.createElement('td')
      level.textContent = formatNumber(player.level)
      const ping = document.createElement('td')
      ping.textContent = `${formatNumber(player.ping, 0)} ms`
      ping.className = pingClass(player.ping)
      const buildings = document.createElement('td')
      buildings.textContent = formatNumber(player.building_count)
      const session = document.createElement('td')
      const currentSession = document.createElement('strong')
      currentSession.textContent = formatDuration(player.session?.current_session)
      const weeklySession = document.createElement('small')
      weeklySession.textContent = `${formatDuration(player.session?.online_7d)} negli ultimi 7g`
      session.append(currentSession, weeklySession)
      const coords = document.createElement('td')
      const code = document.createElement('code')
      code.textContent = mapped
        ? `X ${formatNumber(player.location_x, 0)} · Y ${formatNumber(player.location_y, 0)}`
        : 'Posizione non disponibile'
      coords.appendChild(code)
      row.append(identity, level, ping, buildings, session, coords)
      elements.playersTable.appendChild(row)
    }
    if (focusedId) {
      elements.playersTable.querySelector(`[data-player-id="${focusedId}"]`)?.focus({ preventScroll: true })
    }
  }

  function renderMobilePlayers(players) {
    if (!elements.mobilePlayers) return
    elements.mobilePlayers.replaceChildren()
    if (!players.length) {
      const empty = document.createElement('p')
      empty.className = 'empty-copy'
      empty.textContent = 'Nessun giocatore online.'
      elements.mobilePlayers.appendChild(empty)
      return
    }
    for (const player of players) {
      const card = document.createElement('article')
      card.className = 'mobile-player-card'
      const color = playerColor(player.id)
      const avatar = document.createElement('i')
      avatar.textContent = initials(player.name)
      avatar.style.backgroundColor = color
      avatar.style.color = contrastColor(color)
      const identity = document.createElement('div')
      const name = document.createElement('strong')
      name.textContent = player.name
      const account = document.createElement('small')
      account.textContent = player.accountName || 'account non disponibile'
      identity.append(name, account)
      const ping = document.createElement('span')
      ping.className = pingClass(player.ping)
      ping.textContent = `${formatNumber(player.ping)} ms`
      const stats = document.createElement('p')
      stats.textContent = `Lv.${formatNumber(player.level)} · ${formatNumber(player.building_count)} costruzioni · sessione ${formatDuration(player.session?.current_session)}`
      const profile = document.createElement('a')
      profile.className = 'player-profile-link'
      profile.href = `/giocatori/${encodeURIComponent(player.id)}/`
      profile.textContent = 'Profilo'
      card.append(avatar, identity, ping, stats, profile)
      elements.mobilePlayers.appendChild(card)
    }
  }

  function renderPlayerArchive(players) {
    if (!elements.playerArchive) return
    const expanded = new Set(
      [...elements.playerArchive.querySelectorAll('details[open]')]
        .map((details) => {
          const playerId = details.closest('[data-player-id]')?.dataset.playerId
          return playerId ? `${playerId}:${details.dataset.section || 'details'}` : null
        })
        .filter(Boolean),
    )
    const query = state.playerQuery.trim().toLocaleLowerCase('it')
    const visiblePlayers = players
      .filter((player) => !state.favoritesOnly || state.favoritePlayers.has(player.id))
      .filter((player) => !query || `${player.name} ${player.accountName}`.toLocaleLowerCase('it').includes(query))
      .sort((left, right) => {
        const favoriteDifference = Number(state.favoritePlayers.has(right.id)) - Number(state.favoritePlayers.has(left.id))
        return favoriteDifference || left.name.localeCompare(right.name, 'it', { sensitivity: 'base' })
      })
    elements.playerArchive.replaceChildren()
    setText(
      elements.playerArchiveStatus,
      `${formatNumber(visiblePlayers.length)} di ${formatNumber(players.length)} giocatori · aggiornato ${formatDate(state.archiveUpdated)}`,
    )
    if (!visiblePlayers.length) {
      const empty = document.createElement('p')
      empty.className = 'empty-copy'
      empty.textContent = players.length ? 'Nessun giocatore corrisponde ai filtri.' : 'Nessun giocatore registrato.'
      elements.playerArchive.appendChild(empty)
      return
    }

    for (const player of visiblePlayers) {
      const card = document.createElement('article')
      card.className = 'player-history-card'
      card.dataset.playerId = player.id

      const header = document.createElement('header')
      const avatar = document.createElement('i')
      avatar.className = 'history-avatar'
      avatar.textContent = initials(player.name)
      const color = playerColor(player.id)
      avatar.style.backgroundColor = color
      avatar.style.color = contrastColor(color)
      const identity = document.createElement('div')
      const name = document.createElement('strong')
      name.textContent = player.name
      const account = document.createElement('small')
      account.textContent = player.save_only
        ? 'Personaggio storico dal salvataggio'
        : (player.accountName || 'account non disponibile')
      identity.append(name, account)
      const status = document.createElement('span')
      status.className = player.online
        ? 'archive-status online'
        : `archive-status${player.save_only ? ' saved' : ''}`
      const firstSeenDate = new Date(player.first_seen)
      const isNew = Number.isFinite(firstSeenDate.getTime()) && (Date.now() - firstSeenDate.getTime()) < 7 * 86400 * 1000
      if (player.online) {
        status.textContent = 'Online ora'
      } else if (player.save_only) {
        status.textContent = 'Storico del mondo'
      } else if (isNew) {
        status.textContent = 'Nuovo esploratore'
      } else {
        status.textContent = `Ultimo accesso ${formatFullDate(player.last_seen)}`
      }
      const favorite = document.createElement('button')
      const isFavorite = state.favoritePlayers.has(player.id)
      favorite.type = 'button'
      favorite.className = 'favorite-toggle'
      favorite.textContent = isFavorite ? '★' : '☆'
      favorite.setAttribute('aria-label', `${isFavorite ? 'Rimuovi' : 'Aggiungi'} ${player.name} dai preferiti locali`)
      favorite.setAttribute('aria-pressed', String(isFavorite))
      favorite.addEventListener('click', () => {
        if (state.favoritePlayers.has(player.id)) state.favoritePlayers.delete(player.id)
        else state.favoritePlayers.add(player.id)
        writeStorage('observatory.favoritePlayers', JSON.stringify([...state.favoritePlayers]))
        renderPlayerArchive(state.archivePlayers)
      })
      const identityControls = document.createElement('div')
      identityControls.className = 'archive-identity-controls'
      identityControls.append(identity)
      if (!player.save_only) {
        const profile = document.createElement('a')
        profile.className = 'player-profile-link'
        profile.href = `/giocatori/${encodeURIComponent(player.id)}/`
        profile.textContent = 'Profilo'
        identityControls.appendChild(profile)
      }
      header.append(avatar, identityControls, status, favorite)

      const progression = document.createElement('dl')
      progression.className = 'player-progression-grid'
      const pingAverage = player.ping_7d?.sample_count
        ? `${formatNumber(player.ping_7d.average, 0)} ms · ${formatNumber(player.ping_7d.minimum, 0)}–${formatNumber(player.ping_7d.maximum, 0)}`
        : '--'
      const progressionRows = [
        ['Livello', `Lv. ${formatNumber(player.level)}`],
        ['Esperienza', player.save_available ? formatNumber(player.exp) : '--'],
        ['Pal posseduti', player.save_available ? formatNumber(player.owned_pal_count) : '--'],
        ['Costruzioni', player.save_only ? '--' : formatNumber(player.building_count)],
        ['Gilda', player.guild_name ? `${player.guild_name}${player.is_guild_admin ? ' · capogilda' : ''}` : '--'],
        ['Ping medio 7g', pingAverage],
      ]
      for (const [label, value] of progressionRows) {
        const item = document.createElement('div')
        const term = document.createElement('dt')
        term.textContent = label
        const description = document.createElement('dd')
        description.textContent = value
        item.append(term, description)
        progression.appendChild(item)
      }

      const totals = document.createElement('dl')
      totals.className = 'player-time-grid'
      for (const [label, value] of [
        ['Ultimi 30 giorni', formatDuration(Number(player.minutes_30d) * 60)],
        ['Ultimi 365 giorni', formatDuration(Number(player.minutes_365d) * 60)],
        ['Da sempre', formatDuration(Number(player.minutes_all) * 60)],
        ['Media sessione', formatDuration(Number(player.average_session_minutes) * 60)],
        ['Sessione più lunga', formatDuration(Number(player.longest_session_minutes) * 60)],
        ['Giorni attivi 30g', formatNumber(player.active_days_30d)],
      ]) {
        const item = document.createElement('div')
        const term = document.createElement('dt')
        term.textContent = label
        const description = document.createElement('dd')
        description.textContent = value
        item.append(term, description)
        totals.appendChild(item)
      }

      const meta = document.createElement('p')
      meta.className = 'player-history-meta'
      const sessionLabel = Number(player.session_count) === 1 ? 'sessione' : 'sessioni'
      meta.textContent = player.first_seen
        ? `Prima visita ${formatFullDate(player.first_seen)} · ${formatNumber(player.session_count)} ${sessionLabel}`
        : 'Personaggio recuperato dal Level.sav · nessuna sessione registrata dal sito'
      card.append(header, progression)
      if (!player.save_only) card.appendChild(totals)
      card.appendChild(meta)

      const statusPointLabels = [
        ['max_hp', 'HP massimo'],
        ['stamina', 'Stamina'],
        ['attack', 'Attacco'],
        ['carry_weight', 'Peso trasportabile'],
        ['capture_rate', 'Cattura'],
        ['work_speed', 'Velocità lavoro'],
      ]
      const visibleStatusPoints = statusPointLabels.filter(([key]) => Number(player.status_points?.[key]) > 0)
      if (visibleStatusPoints.length || Number(player.unused_status_points) > 0) {
        const details = document.createElement('details')
        details.dataset.section = 'stats'
        details.open = expanded.has(`${player.id}:stats`)
        const summary = document.createElement('summary')
        summary.textContent = 'Punti statistiche personaggio'
        const stats = document.createElement('dl')
        stats.className = 'player-stat-grid'
        for (const [key, label] of visibleStatusPoints) {
          const item = document.createElement('div')
          const term = document.createElement('dt')
          term.textContent = label
          const description = document.createElement('dd')
          description.textContent = formatNumber(player.status_points[key])
          item.append(term, description)
          stats.appendChild(item)
        }
        if (Number(player.unused_status_points) > 0) {
          const item = document.createElement('div')
          const term = document.createElement('dt')
          term.textContent = 'Punti inutilizzati'
          const description = document.createElement('dd')
          description.textContent = formatNumber(player.unused_status_points)
          item.append(term, description)
          stats.appendChild(item)
        }
        details.append(summary, stats)
        card.appendChild(details)
      }

      if (player.periods?.length) {
        const details = document.createElement('details')
        details.dataset.section = 'sessions'
        details.open = expanded.has(`${player.id}:sessions`)
        const summary = document.createElement('summary')
        summary.textContent = `Periodi online (${formatNumber(player.periods.length)})`
        const periods = document.createElement('ol')
        periods.className = 'session-periods'
        for (const period of player.periods) {
          const item = document.createElement('li')
          const range = document.createElement('span')
          range.textContent = period.active
            ? `Dal ${formatFullDate(period.started_at)} · in corso`
            : `${formatFullDate(period.started_at)} → ${formatFullDate(period.ended_at)}`
          const duration = document.createElement('strong')
          duration.textContent = `${formatNumber(period.duration_minutes)} min`
          item.append(range, duration)
          periods.appendChild(item)
        }
        details.append(summary, periods)
        card.appendChild(details)
      }
      elements.playerArchive.appendChild(card)
    }
  }

  async function loadPlayerArchive() {
    try {
      const data = await requestJson('/api/v1/players', 'playerArchive')
      state.archivePlayers = data.players || []
      state.archiveUpdated = data.generated_at
      renderPlayerArchive(state.archivePlayers)
    } catch (error) {
      if (error.name === 'AbortError') return
      if (!state.archivePlayers.length) renderPlayerArchive([])
      setText(elements.playerArchiveStatus, 'Storico temporaneamente non disponibile.')
    }
  }

  const settingGroups = [
    ['Progressione', ['Difficulty', 'ExpRate', 'PalCaptureRate', 'PalSpawnNumRate', 'WorkSpeedRate', 'PalEggDefaultHatchingTime']],
    ['Tempo e risorse', ['DayTimeSpeedRate', 'NightTimeSpeedRate', 'CollectionDropRate', 'CollectionObjectHpRate', 'CollectionObjectRespawnSpeedRate', 'EnemyDropItemRate', 'DropItemMaxNum', 'DropItemAliveMaxHours']],
    ['Giocatori', ['PlayerDamageRateAttack', 'PlayerDamageRateDefense', 'PlayerStomachDecreaceRate', 'PlayerStaminaDecreaceRate', 'PlayerAutoHPRegeneRate', 'PlayerAutoHpRegeneRateInSleep', 'DeathPenalty', 'bEnableFriendlyFire']],
    ['Pal', ['PalDamageRateAttack', 'PalDamageRateDefense', 'PalStomachDecreaceRate', 'PalStaminaDecreaceRate', 'PalAutoHPRegeneRate', 'PalAutoHpRegeneRateInSleep']],
    ['Basi e gilde', ['BaseCampMaxNum', 'BaseCampWorkerMaxNum', 'GuildPlayerMaxNum', 'BuildObjectDamageRate', 'BuildObjectDeteriorationDamageRate', 'bAutoResetGuildNoOnlinePlayers', 'AutoResetGuildTimeNoOnlinePlayers', 'bCanPickupOtherGuildDeathPenaltyDrop', 'bEnableDefenseOtherGuildPlayer']],
    ['Multiplayer', ['ServerPlayerMaxNum', 'CoopPlayerMaxNum', 'bIsPvP', 'bEnablePlayerToPlayerDamage', 'bEnableFastTravel', 'bEnableNonLoginPenalty', 'CrossplayPlatforms', 'AllowConnectPlatform']],
    ['Mondo e salvataggi', ['bEnableInvaderEnemy', 'bIsStartLocationSelectByMap', 'bExistPlayerAfterLogout', 'bIsUseBackupSaveData']],
    ['Identità server', ['ServerName', 'ServerDescription']],
  ]

  const settingLabels = {
    AllowConnectPlatform: 'Piattaforme consentite',
    CrossplayPlatforms: 'Piattaforme crossplay',
    ServerDescription: 'Descrizione server',
    ServerName: 'Nome server',
    bExistPlayerAfterLogout: 'Giocatore persistente dopo il logout',
    bIsUseBackupSaveData: 'Backup dei salvataggi',
  }

  function settingLabel(key) {
    return settingLabels[key] || key.replace(/^b(?=[A-Z])/, '').replace(/([a-z0-9])([A-Z])/g, '$1 $2').replaceAll('_', ' ')
  }

  function settingValue(value) {
    if (Array.isArray(value)) return value.map(settingValue).join(', ')
    if (value === null || value === undefined || value === '') return '--'
    if (value === true) return 'Attivo'
    if (value === false) return 'Disattivo'
    if (typeof value === 'number') return formatNumber(value, 4)
    return String(value)
  }

  function renderServerProfile(data) {
    if (!elements.serverProfile) return
    elements.serverProfile.replaceChildren()
    const settings = data.settings || {}
    const metrics = data.metrics || {}
    const status = data.status || {}
    const platforms = settings.CrossplayPlatforms ?? settings.AllowConnectPlatform
    const profile = [
      ['Stato', status.online ? 'Operativo' : (status.stale ? 'Dati obsoleti' : 'Non raggiungibile')],
      ['Modalità', Object.hasOwn(settings, 'bIsPvP') ? (settings.bIsPvP ? 'PvP' : 'PvE') : null],
      ['Giocatori', Object.hasOwn(metrics, 'currentplayernum') && Object.hasOwn(metrics, 'maxplayernum') ? `${formatNumber(metrics.currentplayernum)} / ${formatNumber(metrics.maxplayernum)}` : null],
      ['Avviato', status.started_at ? formatDate(status.started_at, true) : null],
      ['Versione', data.info?.version || null],
      ['Piattaforme', platforms === undefined ? null : settingValue(platforms)],
      ['Backup salvataggi', Object.hasOwn(settings, 'bIsUseBackupSaveData') ? (settings.bIsUseBackupSaveData ? 'Attivo' : 'Disattivo') : null],
      ['Invasori', Object.hasOwn(settings, 'bEnableInvaderEnemy') ? (settings.bEnableInvaderEnemy ? 'Attivi' : 'Disattivi') : null],
    ]
    for (const [label, value] of profile) {
      if (value === null) continue
      const item = document.createElement('div')
      const term = document.createElement('dt')
      term.textContent = label
      const description = document.createElement('dd')
      description.textContent = value
      item.append(term, description)
      elements.serverProfile.appendChild(item)
    }
  }

  function renderWorldHighlights(settings) {
    if (!elements.worldHighlights) return
    elements.worldHighlights.replaceChildren()
    const highlights = [
      ['Modalità', Object.hasOwn(settings, 'bIsPvP') ? (settings.bIsPvP ? 'PvP' : 'PvE') : null],
      ['Esperienza', Object.hasOwn(settings, 'ExpRate') ? `× ${formatNumber(settings.ExpRate, 2)}` : null],
      ['Raccolta', Object.hasOwn(settings, 'CollectionDropRate') ? `× ${formatNumber(settings.CollectionDropRate, 2)}` : null],
      ['Viaggio rapido', Object.hasOwn(settings, 'bEnableFastTravel') ? (settings.bEnableFastTravel ? 'Attivo' : 'Disattivo') : null],
      ['Capacità', Object.hasOwn(settings, 'ServerPlayerMaxNum') ? `${formatNumber(settings.ServerPlayerMaxNum)} giocatori` : null],
    ]
    for (const [label, value] of highlights) {
      if (value === null) continue
      const card = document.createElement('article')
      card.className = 'world-highlight'
      const caption = document.createElement('span')
      caption.textContent = label
      const content = document.createElement('strong')
      content.textContent = value
      card.append(caption, content)
      elements.worldHighlights.appendChild(card)
    }
  }

  function renderSettings(settings) {
    if (!elements.settingsGrid) return
    elements.settingsGrid.replaceChildren()
    renderWorldHighlights(settings)
    if (!Object.keys(settings).length) {
      const empty = document.createElement('p')
      empty.className = 'empty-copy'
      empty.textContent = 'Configurazione non ancora ricevuta.'
      elements.settingsGrid.appendChild(empty)
      return
    }
    const query = elements.settingsSearch.value.trim().toLocaleLowerCase('it')
    let rendered = 0
    for (const [title, keys] of settingGroups) {
      const available = keys.filter((key) => {
        if (!Object.hasOwn(settings, key)) return false
        if (!query) return true
        return `${settingLabel(key)} ${settingValue(settings[key])}`.toLocaleLowerCase('it').includes(query)
      })
      if (!available.length) continue
      const group = document.createElement('article')
      group.className = 'settings-group'
      const heading = document.createElement('h3')
      heading.textContent = title
      group.appendChild(heading)
      for (const key of available) {
        const row = document.createElement('div')
        row.className = 'setting-row'
        const label = document.createElement('span')
        label.textContent = settingLabel(key)
        const value = document.createElement('strong')
        value.textContent = settingValue(settings[key])
        row.append(label, value)
        group.appendChild(row)
      }
      elements.settingsGrid.appendChild(group)
      rendered += available.length
    }
    if (!rendered) {
      const empty = document.createElement('p')
      empty.className = 'empty-copy'
      empty.textContent = 'Nessuna regola corrisponde alla ricerca.'
      elements.settingsGrid.appendChild(empty)
    }
  }

  function renderEvents(events) {
    if (!elements.eventList) return
    elements.eventList.replaceChildren()
    if (!events.length) {
      const empty = document.createElement('li')
      empty.className = 'empty-copy'
      empty.textContent = 'Nessun evento registrato.'
      elements.eventList.appendChild(empty)
      return
    }
    for (const event of events) {
      const item = document.createElement('li')
      item.className = event.type
      const dot = document.createElement('i')
      const copy = document.createElement('span')
      const player = document.createElement('strong')
      player.textContent = event.player
      copy.append(player, document.createTextNode(event.type === 'join' ? ' è entrato nel mondo' : ' ha lasciato il mondo'))
      const time = document.createElement('time')
      time.dateTime = event.timestamp
      time.textContent = formatDate(event.timestamp, true)
      item.append(dot, copy, time)
      elements.eventList.appendChild(item)
    }
  }

  function renderSnapshot(data) {
    state.snapshot = data
    const metrics = data.metrics || {}
    const players = data.players || []
    const online = Boolean(data.status?.online)
    const stale = Boolean(data.status?.stale)

    if (elements.headerStatus) {
      elements.headerStatus.classList.toggle('online', online)
      elements.headerStatus.classList.toggle('offline', !online)
      setText(elements.headerStatus.querySelector('b'), online ? 'ONLINE' : (stale ? 'DATI OBSOLETI' : 'OFFLINE'))
    }
    setText(elements.serverName, data.info?.servername || 'Palworld Server')
    setText(elements.serverDescription, data.info?.description || 'Telemetria riservata del server dedicato.')
    setText(elements.serverVersion, data.info?.version || '--')
    setText(elements.lastUpdate, formatDate(data.status?.last_updated))
    if (elements.lastUpdate) elements.lastUpdate.dateTime = data.status?.last_updated || ''
    setText(elements.heroPlayers, formatNumber(metrics.currentplayernum ?? players.length))
    setText(elements.heroCapacity, `/ ${formatNumber(metrics.maxplayernum)}`)
    setText(elements.heroFps, formatNumber(metrics.serverfps, 1))
    setText(elements.heroUptime, formatDuration(metrics.uptime))
    setText(elements.heroDay, formatNumber(metrics.days))
    const dataAge = data.status?.data_age_seconds
    setText(elements.signalAge, dataAge == null ? '--' : `${dataAge}s`)
    if (elements.signalBar) elements.signalBar.style.width = dataAge == null ? '0%' : `${Math.max(0, 100 - Math.min(100, dataAge / 1.2))}%`
    setText(elements.metricFpsAverage, formatNumber(data.summary_24h?.average_fps, 1))
    setText(elements.metricFpsMinimum, formatNumber(data.summary_24h?.minimum_fps, 1))
    setText(elements.metricFrameTime, formatNumber(metrics.serverframetime, 2))
    setText(elements.metricPeak, formatNumber(data.summary_24h?.peak_players))
    setText(elements.metricPlayersAverage, formatNumber(data.summary_24h?.average_players, 1))
    setText(elements.metricBases, formatNumber(metrics.basecampnum))

    setText(elements.heroDayHome, formatNumber(metrics.days))
    setText(elements.heroFpsHome, formatNumber(metrics.serverfps, 1))
    setText(elements.heroUptimeHome, formatDuration(metrics.uptime))
    setText(elements.lastUpdateHome, formatDate(data.status?.last_updated))
    if (elements.lastUpdateHome) elements.lastUpdateHome.dateTime = data.status?.last_updated || ''

    if (state.worldSaveData) renderWorldSaveStatus(state.worldSaveData)
    renderPlayersTable(players)
    renderMobilePlayers(players)
    renderServerProfile(data)
    renderSettings(data.settings || {})
    renderFilteredEvents()
    renderOnlineComparison(data)

    const staleMessage = data.status?.reachable
      ? 'Il collegamento è attivo, ma la telemetria è aggiornata in ritardo.'
      : 'Il server non è raggiungibile e gli ultimi dati disponibili sono obsoleti.'
    setNotice('snapshot', stale ? staleMessage : null)
  }

  function chartScale(samples) {
    const fpsValues = samples.map((sample) => Number(sample.fps) || 0)
    const minimum = Math.min(...fpsValues)
    const maximum = Math.max(...fpsValues)
    const minFps = Math.max(0, Math.floor((minimum - 2) / 5) * 5)
    const maxFps = Math.max(minFps + 5, Math.ceil((maximum + 2) / 5) * 5)
    const observedMaxPlayers = Math.max(0, ...samples.map((sample) => Number(sample.players) || 0))
    const observedMaxBases = Math.max(0, ...samples.map((sample) => Number(sample.bases) || 0))
    return {
      minFps,
      maxFps,
      maxPlayers: Math.max(1, observedMaxPlayers, observedMaxBases),
      observedMaxPlayers,
      observedMaxBases,
    }
  }

  function renderFpsHealth(health = {}) {
    if (!elements.performanceHealth) return
    elements.performanceHealth.dataset.state = health.state || 'no_data'
    setText(elements.healthLabel, health.label || 'Nessun dato')
    setText(elements.healthScore, health.score == null ? '--' : `${formatNumber(health.score)} / 100`)
    if (health.state === 'ok') {
      setText(
        elements.healthDetail,
        `Mediana ${formatNumber(health.median_fps, 1)} FPS · ultimi 10m ${formatNumber(health.recent_median_fps, 1)} · sotto 30 FPS ${formatNumber(health.under_30_percent, 1)}% · calo più lungo ${formatShortDuration(health.longest_dip_seconds)}.`,
      )
    } else if (health.state === 'calibrating') {
      setText(elements.healthDetail, `Raccolti ${formatDuration(health.coverage_seconds)} di campioni; servono almeno 5 minuti.`)
    } else if (health.state === 'stale') {
      setText(elements.healthDetail, 'Il campione FPS più recente ha oltre cinque minuti: il giudizio è sospeso.')
    } else {
      setText(elements.healthDetail, 'Il giudizio richiede almeno cinque minuti di campioni.')
    }
  }

  function updateChartTooltip() {
    if (!elements.chartTooltip) return
    const point = state.chartPoints[state.chartHoverIndex]
    if (!point) {
      elements.chartTooltip.hidden = true
      return
    }
    elements.chartTooltip.replaceChildren()
    const time = document.createElement('strong')
    time.textContent = formatDate(point.sample.timestamp, true)
    const fps = document.createElement('span')
    fps.textContent = `${formatNumber(point.sample.fps, 1)} FPS`
    const players = document.createElement('span')
    players.textContent = `${formatNumber(point.sample.players)} giocatori`
    const bases = document.createElement('span')
    bases.className = 'bases'
    bases.textContent = `${formatNumber(point.sample.bases)} campi base`
    elements.chartTooltip.append(time, fps, players, bases)
    elements.chartTooltip.hidden = false
    const canvasLeft = elements.historyChart.offsetLeft
    const canvasTop = elements.historyChart.offsetTop
    const tooltipWidth = elements.chartTooltip.offsetWidth
    const cardWidth = elements.historyChart.parentElement.clientWidth
    elements.chartTooltip.style.left = `${Math.min(cardWidth - tooltipWidth - 8, Math.max(8, canvasLeft + point.x + 12))}px`
    elements.chartTooltip.style.top = `${Math.max(42, canvasTop + point.yFps - 38)}px`
  }

  function drawChart(samples = state.historySamples) {
    const canvas = elements.historyChart
    if (!canvas) return
    const context = canvas.getContext('2d')
    const rect = canvas.getBoundingClientRect()
    const ratio = window.devicePixelRatio || 1
    canvas.width = Math.max(1, Math.floor(rect.width * ratio))
    canvas.height = Math.max(1, Math.floor(300 * ratio))
    context.scale(ratio, ratio)
    context.clearRect(0, 0, rect.width, 300)

    const validSamples = samples
      .filter((sample) => Number.isFinite(new Date(sample.timestamp).getTime()))
      .sort((left, right) => new Date(left.timestamp) - new Date(right.timestamp))
    elements.chartEmpty.hidden = validSamples.length > 1
    state.chartPoints = []
    if (validSamples.length < 2) {
      elements.chartTooltip.hidden = true
      setText(elements.chartSummary, 'Nessun campione storico disponibile.')
      return
    }

    const width = rect.width
    const height = 300
    const pad = { left: 48, right: 48, top: 20, bottom: 34 }
    const plotWidth = Math.max(1, width - pad.left - pad.right)
    const plotHeight = height - pad.top - pad.bottom
    const firstTime = Number.isFinite(new Date(state.historyWindow?.from).getTime())
      ? new Date(state.historyWindow.from).getTime()
      : new Date(validSamples[0].timestamp).getTime()
    const lastTime = Number.isFinite(new Date(state.historyWindow?.to).getTime())
      ? new Date(state.historyWindow.to).getTime()
      : new Date(validSamples[validSamples.length - 1].timestamp).getTime()
    const timeSpan = Math.max(1, lastTime - firstTime)
    const { minFps, maxFps, maxPlayers, observedMaxPlayers, observedMaxBases } = chartScale(validSamples)
    const observedMinFps = Math.min(...validSamples.map((sample) => Number(sample.fps) || 0))
    const observedMaxFps = Math.max(...validSamples.map((sample) => Number(sample.fps) || 0))
    setText(elements.chartSummary, `Storico di ${validSamples.length} campioni. FPS da ${formatNumber(observedMinFps, 1)} a ${formatNumber(observedMaxFps, 1)}; massimo ${formatNumber(observedMaxPlayers)} giocatori e ${formatNumber(observedMaxBases)} campi base online.`)

    context.strokeStyle = 'rgba(196,220,199,.13)'
    context.fillStyle = '#8ea29a'
    context.font = '11px ui-monospace, monospace'
    context.lineWidth = 1
    for (let index = 0; index <= 4; index += 1) {
      const y = pad.top + (plotHeight * index) / 4
      context.beginPath()
      context.moveTo(pad.left, y)
      context.lineTo(width - pad.right, y)
      context.stroke()
      const fpsLabel = maxFps - ((maxFps - minFps) * index) / 4
      const playerLabel = maxPlayers - (maxPlayers * index) / 4
      context.fillText(formatNumber(fpsLabel, 0), 7, y + 4)
      const rightLabel = formatNumber(playerLabel, playerLabel < 4 ? 1 : 0)
      context.fillText(rightLabel, width - pad.right + 9, y + 4)
    }

    state.chartPoints = validSamples.map((sample) => {
      const x = pad.left + ((new Date(sample.timestamp).getTime() - firstTime) / timeSpan) * plotWidth
      const fpsRatio = ((Number(sample.fps) || 0) - minFps) / (maxFps - minFps)
      const playerRatio = (Number(sample.players) || 0) / maxPlayers
      const basesRatio = (Number(sample.bases) || 0) / maxPlayers
      return {
        sample,
        x,
        yFps: pad.top + plotHeight - fpsRatio * plotHeight,
        yPlayers: pad.top + plotHeight - playerRatio * plotHeight,
        yBases: pad.top + plotHeight - basesRatio * plotHeight,
      }
    })

    const drawLine = (field, color) => {
      context.beginPath()
      context.strokeStyle = color
      context.lineWidth = 2
      state.chartPoints.forEach((point, index) => {
        const hasGap = index > 0 && point.sample.gap_before === true
        if (index === 0 || hasGap) context.moveTo(point.x, point[field])
        else context.lineTo(point.x, point[field])
      })
      context.stroke()
      for (const point of state.chartPoints) {
        context.fillStyle = color
        context.beginPath()
        context.arc(point.x, point[field], 1.5, 0, Math.PI * 2)
        context.fill()
      }
    }
    const styles = getComputedStyle(document.documentElement)
    const fpsColor = styles.getPropertyValue('--teal').trim() || '#4ce0c1'
    const playersColor = styles.getPropertyValue('--coral').trim() || '#ff735c'
    const basesColor = styles.getPropertyValue('--gold').trim() || '#e5b85c'
    drawLine('yFps', fpsColor)
    drawLine('yPlayers', playersColor)
    drawLine('yBases', basesColor)

    const compactLabels = width < 520
    const labels = [
      [formatChartDate(new Date(firstTime).toISOString(), compactLabels, timeSpan), pad.left, 'left'],
      [formatChartDate(new Date(lastTime).toISOString(), compactLabels, timeSpan), width - pad.right, 'right'],
    ]
    if (width >= 520) {
      labels.splice(1, 0, [formatChartDate(new Date(firstTime + timeSpan / 2).toISOString(), false, timeSpan), pad.left + plotWidth / 2, 'center'])
    }
    context.fillStyle = '#8ea29a'
    for (const [label, x, alignment] of labels) {
      context.textAlign = alignment
      context.fillText(label, x, height - 8)
    }
    context.textAlign = 'left'

    const hovered = state.chartPoints[state.chartHoverIndex]
    if (hovered) {
      context.strokeStyle = 'rgba(233,224,197,.35)'
      context.beginPath()
      context.moveTo(hovered.x, pad.top)
      context.lineTo(hovered.x, pad.top + plotHeight)
      context.stroke()
      for (const [y, color] of [[hovered.yFps, fpsColor], [hovered.yPlayers, playersColor], [hovered.yBases, basesColor]]) {
        context.fillStyle = color
        context.beginPath()
        context.arc(hovered.x, y, 4, 0, Math.PI * 2)
        context.fill()
      }
    }
    updateChartTooltip()
  }

  function setChartHover(index) {
    if (!state.chartPoints.length) return
    state.chartHoverIndex = Math.max(0, Math.min(state.chartPoints.length - 1, index))
    drawChart()
  }

  async function loadHistory() {
    if (!elements.historyRange) return
    const requestedRange = elements.historyRange.value
    try {
      const data = await requestJson(`/api/v1/history?range=${encodeURIComponent(requestedRange)}`, 'history')
      if (requestedRange !== elements.historyRange.value) return
      state.historySamples = data.samples || []
      state.historyWindow = data.window || null
      state.chartHoverIndex = null
      renderFpsHealth(data.fps_health)
      setNotice('history')
      setText(elements.chartEmpty, 'Lo storico inizierà a popolarsi con gli aggiornamenti del collector.')
      drawChart()
    } catch (error) {
      if (error.name === 'AbortError') return
      setNotice('history', 'Lo storico non è raggiungibile: continuo a mostrare gli ultimi campioni ricevuti.', true)
      if (!state.historySamples.length) {
        setText(elements.chartEmpty, 'Storico temporaneamente non disponibile.')
        drawChart()
      }
    }
  }

  function formatPercent(value, digits = 1) {
    const number = finiteNumber(value)
    return number === null ? '--' : `${formatNumber(number, digits)}%`
  }

  function finiteNumber(value) {
    if (value === null || value === undefined || value === '') return null
    const number = Number(value)
    return Number.isFinite(number) ? number : null
  }

  function stabilityLabel(cv) {
    const value = finiteNumber(cv)
    if (value === null) return '--'
    if (value <= 0.05) return 'Molto stabile'
    if (value <= 0.12) return 'Stabile'
    if (value <= 0.25) return 'Variabile'
    return 'Instabile'
  }

  async function loadTelemetryStats() {
    if (!elements.telemetryStats) return
    try {
      const data = await requestJson('/api/v1/telemetry/stats', 'telemetryStats', 10000)
      const uptime = data.uptime || {}
      const fps = data.fps || {}
      const players = data.players || {}
      const world = data.world || {}
      setText(elements.uptime24h, uptime.pct_24h == null ? '--' : formatPercent(uptime.pct_24h))
      setText(elements.uptime7d, uptime.pct_7d == null ? '--' : formatPercent(uptime.pct_7d))
      setText(elements.fpsStability, stabilityLabel(fps.stability_cv_24h))
      setText(elements.worldDay, world.day == null ? '--' : formatNumber(world.day))
      setText(elements.telemetryFpsAvg, fps.mean_24h == null ? '--' : formatNumber(fps.mean_24h, 1))
      setText(elements.telemetryPlayersAvg, players.average_24h == null ? '--' : formatNumber(players.average_24h, 1))
      const gaps = Array.isArray(uptime.gaps_24h) ? uptime.gaps_24h : []
      const gapsCount = elements.dataGaps?.querySelector('#dataGapsCount') || document.getElementById('dataGapsCount')
      if (gapsCount) setText(gapsCount, `${formatNumber(uptime.gap_count_24h || gaps.length)} interruzioni`)
      if (elements.dataGaps) {
        elements.dataGaps.replaceChildren()
        if (!gaps.length) {
          const item = document.createElement('li')
          item.className = 'complete'
          item.textContent = 'Nessuna interruzione rilevata'
          elements.dataGaps.appendChild(item)
        } else {
          for (const gap of gaps) {
            const item = document.createElement('li')
            const minutes = Math.round((gap.seconds || 0) / 60)
            item.textContent = `${formatDate(gap.from, true)} · ${formatNumber(minutes)} min`
            elements.dataGaps.appendChild(item)
          }
        }
      }
    } catch (error) {
      if (error.name === 'AbortError') return
    }
  }

  async function loadWorldDiff() {
    if (!elements.worldDiff) return
    try {
      const data = await requestJson('/api/v1/world/diff', 'worldDiff', 10000)
      elements.worldDiff.replaceChildren()
      if (!data.has_settings) {
        const note = document.createElement('p')
        note.className = 'empty-copy'
        note.textContent = 'Configurazione non ancora ricevuta.'
        elements.worldDiff.appendChild(note)
        return
      }
      if (!data.total) {
        const note = document.createElement('p')
        note.className = 'empty-copy'
        note.textContent = 'Nessuna differenza rispetto ai valori vanilla.'
        elements.worldDiff.appendChild(note)
        return
      }
      for (const diff of data.diffs) {
        const row = document.createElement('div')
        row.className = 'setting-row diff-row'
        const label = document.createElement('span')
        label.textContent = settingLabel(diff.key)
        const value = document.createElement('strong')
        value.textContent = `${settingValue(diff.current)} (vanilla: ${settingValue(diff.vanilla)})`
        row.append(label, value)
        elements.worldDiff.appendChild(row)
      }
      const heading = document.createElement('p')
      heading.className = 'archive-note'
      heading.textContent = `${formatNumber(data.total)} impostazioni differiscono dai valori vanilla.`
      elements.worldDiff.appendChild(heading)
    } catch (error) {
      if (error.name === 'AbortError') return
    }
  }

  let eventFilterValue = 'all'
  function renderFilteredEvents() {
    if (!state.snapshot) return
    const events = state.snapshot.events || []
    const filtered = eventFilterValue === 'all' ? events : events.filter((event) => event.type === eventFilterValue)
    renderEvents(filtered)
    if (elements.eventCounts) {
      const joins = events.filter((event) => event.type === 'join').length
      const leaves = events.filter((event) => event.type === 'leave').length
      setText(elements.eventCounts, `${formatNumber(joins)} entrate · ${formatNumber(leaves)} uscite · ${formatNumber(events.length)} totali`)
    }
  }

  function renderOnlineComparison(data) {
    const onlineNow = Number(data.metrics?.currentplayernum ?? data.players?.length ?? 0)
    const average = Number(data.summary_24h?.average_players ?? 0)
    if (elements.onlineNow) setText(elements.onlineNow, formatNumber(onlineNow))
    if (elements.onlineAverage) setText(elements.onlineAverage, formatNumber(average, 1))
    if (elements.homeRecentActivity) {
      const events = data.events || []
      elements.homeRecentActivity.replaceChildren()
      if (!events.length) {
        const item = document.createElement('p')
        item.className = 'empty-copy'
        item.textContent = 'Nessun evento recente.'
        elements.homeRecentActivity.appendChild(item)
      } else {
        const list = document.createElement('ol')
        list.className = 'event-list compact'
        for (const event of events.slice(0, 6)) {
          const item = document.createElement('li')
          item.className = event.type
          const dot = document.createElement('i')
          const copy = document.createElement('span')
          const player = document.createElement('strong')
          player.textContent = event.player
          copy.append(player, document.createTextNode(event.type === 'join' ? ' è entrato' : ' è uscito'))
          const time = document.createElement('time')
          time.dateTime = event.timestamp
          time.textContent = formatDate(event.timestamp, true)
          item.append(dot, copy, time)
          list.appendChild(item)
        }
        elements.homeRecentActivity.appendChild(list)
      }
    }
  }

  function showToast(message, error = false) {
    if (!elements.connectionToast) return
    setText(elements.connectionToast, message)
    elements.connectionToast.classList.toggle('error', error)
    elements.connectionToast.classList.add('visible')
    window.clearTimeout(state.toastTimer)
    state.toastTimer = window.setTimeout(() => elements.connectionToast.classList.remove('visible'), 3500)
  }

  async function loadSnapshot(initial = false) {
    try {
      const data = await requestJson('/api/v1/snapshot', 'snapshot')
      renderSnapshot(data)
      if (initial && elements.serverName) showToast('Collegamento telemetrico stabilito')
      return true
    } catch (error) {
      if (error.name === 'AbortError') return null
      if (initial && elements.serverName) showToast('Dati temporaneamente non disponibili', true)
      if (elements.headerStatus) {
        elements.headerStatus.classList.remove('online')
        elements.headerStatus.classList.add('offline')
        setText(elements.headerStatus.querySelector('b'), 'CONNESSIONE PERSA')
      }
      setNotice('snapshot', 'Collegamento telemetrico interrotto: i valori mostrati sono gli ultimi ricevuti.', true)
      return false
    }
  }

  function bindChartControls() {
    if (!elements.historyChart) return
    elements.historyChart.addEventListener('pointermove', (event) => {
      if (!state.chartPoints.length) return
      const rect = elements.historyChart.getBoundingClientRect()
      const pointerX = event.clientX - rect.left
      let closest = 0
      for (let index = 1; index < state.chartPoints.length; index += 1) {
        if (Math.abs(state.chartPoints[index].x - pointerX) < Math.abs(state.chartPoints[closest].x - pointerX)) closest = index
      }
      if (closest !== state.chartHoverIndex) setChartHover(closest)
    })
    elements.historyChart.addEventListener('pointerleave', () => {
      state.chartHoverIndex = null
      drawChart()
    })
    elements.historyChart.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
      event.preventDefault()
      const current = state.chartHoverIndex ?? (event.key === 'ArrowRight' ? -1 : state.chartPoints.length)
      setChartHover(current + (event.key === 'ArrowRight' ? 1 : -1))
    })
  }

  function bindCredentialControls() {
    const password = $('#palworldPassword')
    const toggle = $('#togglePalworldPassword')
    if (password && toggle) {
      toggle.addEventListener('click', () => {
        const revealed = toggle.getAttribute('aria-pressed') === 'true'
        toggle.setAttribute('aria-pressed', String(!revealed))
        toggle.textContent = revealed ? 'Mostra' : 'Nascondi'
        password.textContent = revealed ? '••••••••' : password.dataset.secret
      })
    }
    for (const button of document.querySelectorAll('[data-copy-target], [data-copy-secret]')) {
      button.addEventListener('click', async () => {
        const targetId = button.dataset.copyTarget || button.dataset.copySecret
        const target = document.getElementById(targetId)
        const value = button.dataset.copySecret ? target?.dataset.secret : target?.textContent
        if (!value || value.startsWith('Non configurat')) return
        try {
          await navigator.clipboard.writeText(value.trim())
          const previous = button.textContent
          button.textContent = 'Copiato'
          window.setTimeout(() => { button.textContent = previous }, 1500)
        } catch (_error) {
          showToast('Copia non disponibile in questo browser', true)
        }
      })
    }
  }

  function renderWorldSaveStatus(data) {
    if (!elements.worldSaveStatus) return
    state.worldSaveData = data
    const world = data.world || {}
    const entries = [
      ['Giorno mondo', formatNumber(state.snapshot?.metrics?.days), 'Tempo di gioco', ''],
      ['Invasioni attive', world.active_raid_count || 0, 'Basi sotto attacco', Number(world.active_raid_count) > 0 ? 'danger' : 'ok'],
      ['Allarmi piattaforme', world.oil_rig_alert_count || 0, 'Oil rig in allerta', Number(world.oil_rig_alert_count) > 0 ? 'warning' : 'ok'],
      ['Piattaforme completate', `${formatNumber(world.oil_rig_cleared_count || 0)}/${formatNumber(world.oil_rig_count || 0)}`, 'Stato salvato', ''],
    ]
    elements.worldSaveStatus.replaceChildren()
    for (const [label, value, detail, className] of entries) {
      const card = document.createElement('article')
      if (className) card.className = className
      const span = document.createElement('span')
      const strong = document.createElement('strong')
      const small = document.createElement('small')
      span.textContent = label
      strong.textContent = value
      small.textContent = detail
      card.append(span, strong, small)
      elements.worldSaveStatus.appendChild(card)
    }
    setText(elements.worldSaveUpdated, `Snapshot aggiornato: ${formatDate(data.updated_at, true)}`)
    elements.worldSaveNotice.hidden = true
  }

  async function loadWorldSaveStatus() {
    if (!elements.worldSaveStatus) return
    try {
      renderWorldSaveStatus(await requestJson('/api/v1/guild/data', 'world-save', 10000))
    } catch (error) {
      if (error.name === 'AbortError') return
      setText(elements.worldSaveNotice, 'Stato del salvataggio temporaneamente non disponibile.')
      elements.worldSaveNotice.hidden = false
      elements.worldSaveNotice.classList.add('error')
    }
  }

  function scheduleWorldSavePoll() {
    window.clearTimeout(state.worldSaveTimer)
    state.worldSaveTimer = window.setTimeout(async () => {
      if (!document.hidden) await loadWorldSaveStatus()
      scheduleWorldSavePoll()
    }, 300000)
  }

  function scheduleHistoryPoll() {
    window.clearTimeout(state.historyTimer)
    state.historyTimer = window.setTimeout(async () => {
      if (!document.hidden) await loadHistory()
      scheduleHistoryPoll()
    }, 60000)
  }

  function scheduleArchivePoll() {
    window.clearTimeout(state.archiveTimer)
    state.archiveTimer = window.setTimeout(async () => {
      if (!document.hidden) await loadPlayerArchive()
      scheduleArchivePoll()
    }, 60000)
  }

  async function snapshotLoop(initial = false) {
    window.clearTimeout(state.snapshotTimer)
    const generation = ++state.snapshotGeneration
    if (document.hidden) {
      state.snapshotTimer = window.setTimeout(() => {
        if (generation === state.snapshotGeneration) snapshotLoop(false)
      }, 20000)
      return
    }
    const success = await loadSnapshot(initial)
    if (generation !== state.snapshotGeneration) return
    if (success === false) state.snapshotFailures += 1
    else if (success === true) state.snapshotFailures = 0
    const delay = Math.min(120000, 20000 * (2 ** Math.min(3, state.snapshotFailures)))
    state.snapshotTimer = window.setTimeout(() => {
      if (generation === state.snapshotGeneration) snapshotLoop(false)
    }, delay)
  }

  function initialize() {
    initializeTheme()
    const navToggle = $('#navToggle')
    const navMenu = $('#navMenu')
    if (navToggle && navMenu) {
      const navDrawer = window.matchMedia('(max-width: 1700px)')
      const setNavOpen = (open) => {
        const drawerOpen = navDrawer.matches && open
        navMenu.classList.toggle('open', drawerOpen)
        if (!drawerOpen && navMenu.contains(document.activeElement)) navToggle.focus({ preventScroll: true })
        navMenu.inert = navDrawer.matches && !drawerOpen
        navMenu.toggleAttribute('aria-hidden', navDrawer.matches && !drawerOpen)
        navToggle.setAttribute('aria-expanded', String(drawerOpen))
        navToggle.setAttribute('aria-label', drawerOpen ? 'Chiudi menu' : 'Apri menu')
      }
      setNavOpen(false)
      navToggle.addEventListener('click', () => {
        setNavOpen(!navMenu.classList.contains('open'))
      })
      navMenu.addEventListener('click', (event) => {
        if (event.target.tagName === 'A' || event.target.tagName === 'BUTTON') {
          setNavOpen(false)
        }
      })
      navDrawer.addEventListener('change', () => setNavOpen(false))
      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && navMenu.classList.contains('open')) {
          setNavOpen(false)
          navToggle.focus()
        }
      })
    }
    try {
      const favorites = JSON.parse(readStorage('observatory.favoritePlayers', '[]'))
      if (Array.isArray(favorites)) state.favoritePlayers = new Set(favorites.filter((value) => typeof value === 'string'))
    } catch (_error) {
      state.favoritePlayers = new Set()
    }
    if (elements.historyChart) bindChartControls()
    bindCredentialControls()
    if (elements.themeSelect) {
      elements.themeSelect.addEventListener('change', (event) => {
        const theme = THEMES.has(event.target.value) ? event.target.value : 'observatory'
        document.documentElement.dataset.theme = theme
        writeStorage('observatory.theme', theme)
        drawChart()
      })
    }
    if (elements.playerSearch) {
      elements.playerSearch.addEventListener('input', (event) => {
        state.playerQuery = event.target.value
        renderPlayerArchive(state.archivePlayers)
      })
    }
    if (elements.favoritesOnly) {
      elements.favoritesOnly.addEventListener('change', (event) => {
        state.favoritesOnly = event.target.checked
        renderPlayerArchive(state.archivePlayers)
      })
    }
    if (elements.settingsSearch) {
      elements.settingsSearch.addEventListener('input', () => renderSettings(state.snapshot?.settings || {}))
    }
    if (elements.eventFilter) {
      elements.eventFilter.addEventListener('change', (event) => {
        eventFilterValue = event.target.value
        renderFilteredEvents()
      })
    }
    if (elements.historyRange) {
      elements.historyRange.addEventListener('change', async () => {
        await loadHistory()
        scheduleHistoryPoll()
      })
    }
    let resizeFrame = null
    const onResize = () => {
      window.cancelAnimationFrame(resizeFrame)
      resizeFrame = window.requestAnimationFrame(() => {
        drawChart()
      })
    }
    window.addEventListener('resize', onResize)
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) return
      snapshotLoop(false)
      if (elements.historyChart) loadHistory().then(scheduleHistoryPoll)
      if (elements.playerArchive) loadPlayerArchive().then(scheduleArchivePoll)
      if (elements.telemetryStats) loadTelemetryStats()
      if (elements.worldDiff) loadWorldDiff()
      if (elements.worldSaveStatus) loadWorldSaveStatus().then(scheduleWorldSavePoll)
    })
    snapshotLoop(true)
    if (elements.historyChart) loadHistory().then(scheduleHistoryPoll)
    if (elements.playerArchive) loadPlayerArchive().then(scheduleArchivePoll)
    if (elements.telemetryStats) loadTelemetryStats()
    if (elements.worldDiff) loadWorldDiff()
    if (elements.worldSaveStatus) loadWorldSaveStatus().then(scheduleWorldSavePoll)
  }

  initialize()
})()
