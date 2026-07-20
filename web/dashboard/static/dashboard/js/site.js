(() => {
  'use strict'

  const WORLD = {
    maxX: 349400,
    maxY: 724400,
    minX: -1099400,
    minY: -724400,
  }

  const state = {
    snapshot: null,
    selectedPlayer: null,
    map: { scale: 1, panX: 0, panY: 0, dragging: false, pointerX: 0, pointerY: 0 },
    points: { fast_travel: [], boss_tower: [] },
    historySamples: [],
    chartPoints: [],
    chartHoverIndex: null,
    requests: {},
    notices: { snapshot: null, history: null },
    historyTimer: null,
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
    mapViewport: $('#mapViewport'),
    mapPlane: $('#mapPlane'),
    mapCoordinate: $('#mapCoordinate'),
    mapEmpty: $('#mapEmpty'),
    playerLayer: $('#playerLayer'),
    fastTravelLayer: $('#fastTravelLayer'),
    towerLayer: $('#towerLayer'),
    trailLayer: $('#trailLayer'),
    mapRoster: $('#mapRoster'),
    rosterCount: $('#rosterCount'),
    mapSelection: $('#mapSelection'),
    selectedPlayerName: $('#selectedPlayerName'),
    selectedPlayerDetail: $('#selectedPlayerDetail'),
    playersTable: $('#playersTable'),
    settingsGrid: $('#settingsGrid'),
    worldHighlights: $('#worldHighlights'),
    eventList: $('#eventList'),
    historyRange: $('#historyRange'),
    historyChart: $('#historyChart'),
    chartEmpty: $('#chartEmpty'),
    chartSummary: $('#chartSummary'),
    chartTooltip: $('#chartTooltip'),
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

  function formatDate(value, includeDate = false) {
    if (!value) return 'mai'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '--'
    const options = includeDate
      ? { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }
      : { hour: '2-digit', minute: '2-digit', second: '2-digit' }
    return new Intl.DateTimeFormat('it-IT', options).format(date)
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
    const notice = state.notices.snapshot || state.notices.history
    elements.dataNotice.hidden = !notice
    elements.dataNotice.classList.toggle('error', Boolean(notice?.error))
    setText(elements.dataNotice, notice?.message || '')
  }

  function setNotice(key, message = null, error = false) {
    state.notices[key] = message ? { message, error } : null
    renderNotice()
  }

  function worldToPercent(x, y) {
    return {
      left: ((Number(y) - WORLD.minY) / (WORLD.maxY - WORLD.minY)) * 100,
      top: ((WORLD.maxX - Number(x)) / (WORLD.maxX - WORLD.minX)) * 100,
    }
  }

  function percentToWorld(left, top) {
    return {
      x: WORLD.maxX - (top / 100) * (WORLD.maxX - WORLD.minX),
      y: WORLD.minY + (left / 100) * (WORLD.maxY - WORLD.minY),
    }
  }

  function mapLocalFromPointer(event) {
    const rect = elements.mapViewport.getBoundingClientRect()
    const centerX = rect.width / 2
    const centerY = rect.height / 2
    const visualX = event.clientX - rect.left
    const visualY = event.clientY - rect.top
    return {
      x: centerX + (visualX - centerX - state.map.panX) / state.map.scale,
      y: centerY + (visualY - centerY - state.map.panY) / state.map.scale,
      width: rect.width,
      height: rect.height,
    }
  }

  function applyMapTransform() {
    const { scale, panX, panY } = state.map
    elements.mapPlane.style.transform = `translate3d(${panX}px, ${panY}px, 0) scale(${scale})`
    elements.mapPlane.style.setProperty('--inverse-scale', String(1 / scale))
  }

  function setZoom(next) {
    const previous = state.map.scale
    state.map.scale = Math.min(5, Math.max(1, next))
    if (state.map.scale === 1) {
      state.map.panX = 0
      state.map.panY = 0
    }
    applyMapTransform()
    return previous !== state.map.scale
  }

  function clearTrail() {
    elements.trailLayer.querySelector('polyline').setAttribute('points', '')
  }

  function clearSelection(render = true) {
    const previousPlayer = state.selectedPlayer
    const restoreFocus = document.activeElement === $('#clearSelection')
    state.selectedPlayer = null
    if (state.requests.trail) state.requests.trail.abort()
    clearTrail()
    elements.mapSelection.hidden = true
    if (render && state.snapshot) renderMap(state.snapshot.players || [])
    if (restoreFocus && previousPlayer) {
      elements.mapRoster.querySelector(`[data-player-id="${previousPlayer}"]`)?.focus({ preventScroll: true })
    }
  }

  function resetMap() {
    state.map.scale = 1
    state.map.panX = 0
    state.map.panY = 0
    clearSelection()
    applyMapTransform()
  }

  function centerPlayer(player) {
    if (!hasMapLocation(player)) return
    const position = worldToPercent(player.location_x, player.location_y)
    const rect = elements.mapViewport.getBoundingClientRect()
    state.map.scale = Math.max(2.2, state.map.scale)
    state.map.panX = ((50 - position.left) / 100) * rect.width * state.map.scale
    state.map.panY = ((50 - position.top) / 100) * rect.height * state.map.scale
    state.selectedPlayer = player.id
    applyMapTransform()
    renderMap(state.snapshot?.players || [])
    if ($('#showTrail').checked) loadTrail(player.id)
  }

  function marker(type, point, label = '') {
    const position = worldToPercent(point[0], point[1])
    const node = document.createElement(type === 'player' ? 'button' : 'span')
    node.className = `map-marker ${type}`
    node.style.left = `${position.left}%`
    node.style.top = `${position.top}%`
    if (type === 'player') node.type = 'button'
    const icon = document.createElement('span')
    node.appendChild(icon)
    if (label) {
      const caption = document.createElement('em')
      caption.textContent = label
      node.appendChild(caption)
    }
    return node
  }

  function renderStaticPoints() {
    elements.fastTravelLayer.replaceChildren()
    elements.towerLayer.replaceChildren()
    for (const point of state.points.fast_travel || []) {
      elements.fastTravelLayer.appendChild(marker('fast', point))
    }
    for (const point of state.points.boss_tower || []) {
      elements.towerLayer.appendChild(marker('tower', point))
    }
  }

  function renderSelection(players) {
    const selected = players.find((player) => player.id === state.selectedPlayer)
    elements.mapSelection.hidden = !selected
    if (!selected) return
    setText(elements.selectedPlayerName, selected.name)
    setText(
      elements.selectedPlayerDetail,
      `Lv.${formatNumber(selected.level)} · ${formatNumber(selected.ping)} ms · X ${formatNumber(selected.location_x)} / Y ${formatNumber(selected.location_y)}`,
    )
  }

  function renderMap(players) {
    const focusedElement = document.activeElement
    const focusedId = focusedElement?.dataset?.playerId
    const focusedLayer = focusedElement?.closest('#playerLayer')
      ? 'marker'
      : (focusedElement?.closest('#mapRoster') ? 'roster' : null)
    elements.playerLayer.replaceChildren()
    elements.mapRoster.replaceChildren()
    setText(elements.rosterCount, String(players.length))
    elements.mapEmpty.classList.toggle('visible', players.length === 0)

    if (!players.length) {
      const empty = document.createElement('p')
      empty.className = 'empty-copy'
      empty.textContent = 'Nessun esploratore rilevato.'
      elements.mapRoster.appendChild(empty)
      clearTrail()
      elements.mapSelection.hidden = true
      return
    }

    for (const player of players) {
      const mapped = hasMapLocation(player)
      if (mapped) {
        const node = marker('player', [player.location_x, player.location_y], `Lv.${player.level} ${player.name}`)
        node.dataset.playerId = player.id
        node.classList.toggle('selected', player.id === state.selectedPlayer)
        node.setAttribute('aria-label', `Centra ${player.name} sulla mappa`)
        node.setAttribute('aria-pressed', String(player.id === state.selectedPlayer))
        node.addEventListener('click', () => centerPlayer(player))
        elements.playerLayer.appendChild(node)
      }

      const roster = document.createElement('button')
      roster.type = 'button'
      roster.dataset.playerId = player.id
      roster.className = 'roster-player'
      roster.classList.toggle('selected', player.id === state.selectedPlayer)
      roster.classList.toggle('unmapped', !mapped)
      roster.setAttribute('aria-pressed', String(player.id === state.selectedPlayer))
      if (!mapped) roster.setAttribute('aria-disabled', 'true')
      const avatar = document.createElement('i')
      avatar.textContent = initials(player.name)
      const identity = document.createElement('span')
      const name = document.createElement('strong')
      name.textContent = player.name
      const detail = document.createElement('small')
      detail.textContent = `Lv.${player.level} · ${formatNumber(player.ping, 0)} ms`
      identity.append(name, detail)
      const coordinate = document.createElement('span')
      coordinate.textContent = mapped
        ? `${formatNumber(player.location_x, 0)} / ${formatNumber(player.location_y, 0)}`
        : 'Posizione non disponibile'
      roster.append(avatar, identity, coordinate)
      if (mapped) roster.addEventListener('click', () => centerPlayer(player))
      elements.mapRoster.appendChild(roster)
    }

    renderSelection(players)
    if (focusedId && focusedLayer) {
      const layer = focusedLayer === 'marker' ? elements.playerLayer : elements.mapRoster
      layer.querySelector(`[data-player-id="${focusedId}"]`)?.focus({ preventScroll: true })
    }
  }

  async function loadTrail(playerId) {
    if (!playerId || !$('#showTrail').checked) {
      clearTrail()
      return
    }
    try {
      const data = await requestJson(`/api/v1/player/${encodeURIComponent(playerId)}/trail?range=6h`, 'trail')
      if (state.selectedPlayer !== playerId || !$('#showTrail').checked) return
      const points = (data.positions || [])
        .filter((position) => Number(position.x) !== 0 || Number(position.y) !== 0)
        .map((position) => {
          const mapped = worldToPercent(position.x, position.y)
          return `${mapped.left * 10},${mapped.top * 10}`
        })
        .join(' ')
      elements.trailLayer.querySelector('polyline').setAttribute('points', points)
    } catch (error) {
      if (error.name !== 'AbortError' && state.selectedPlayer === playerId) clearTrail()
    }
  }

  function renderPlayersTable(players) {
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
      const playerButton = document.createElement('button')
      playerButton.type = 'button'
      playerButton.className = 'player-link'
      playerButton.dataset.playerId = player.id
      const name = document.createElement('strong')
      name.textContent = player.name
      const account = document.createElement('small')
      account.textContent = player.accountName || 'account non disponibile'
      playerButton.append(name, account)
      if (mapped) {
        playerButton.setAttribute('aria-label', `Mostra ${player.name} sulla mappa`)
        playerButton.addEventListener('click', () => centerPlayer(player))
      } else {
        playerButton.setAttribute('aria-disabled', 'true')
      }
      identity.appendChild(playerButton)

      const level = document.createElement('td')
      level.textContent = formatNumber(player.level)
      const ping = document.createElement('td')
      ping.textContent = `${formatNumber(player.ping, 0)} ms`
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

  const settingGroups = [
    ['Progressione', ['Difficulty', 'ExpRate', 'PalCaptureRate', 'PalSpawnNumRate', 'WorkSpeedRate', 'PalEggDefaultHatchingTime']],
    ['Tempo e risorse', ['DayTimeSpeedRate', 'NightTimeSpeedRate', 'CollectionDropRate', 'CollectionObjectHpRate', 'CollectionObjectRespawnSpeedRate', 'EnemyDropItemRate']],
    ['Giocatori', ['PlayerDamageRateAttack', 'PlayerDamageRateDefense', 'PlayerStomachDecreaceRate', 'PlayerStaminaDecreaceRate', 'DeathPenalty', 'bEnableFriendlyFire']],
    ['Pal', ['PalDamageRateAttack', 'PalDamageRateDefense', 'PalStomachDecreaceRate', 'PalStaminaDecreaceRate', 'PalAutoHPRegeneRate']],
    ['Basi e gilde', ['BaseCampMaxNum', 'BaseCampWorkerMaxNum', 'GuildPlayerMaxNum', 'BuildObjectDamageRate', 'BuildObjectDeteriorationDamageRate', 'AutoResetGuildTimeNoOnlinePlayers']],
    ['Multiplayer', ['ServerPlayerMaxNum', 'CoopPlayerMaxNum', 'bIsPvP', 'bEnablePlayerToPlayerDamage', 'bEnableFastTravel', 'AllowConnectPlatform']],
  ]

  function settingLabel(key) {
    return key.replace(/^b(?=[A-Z])/, '').replace(/([a-z0-9])([A-Z])/g, '$1 $2').replaceAll('_', ' ')
  }

  function settingValue(value) {
    if (value === true) return 'Attivo'
    if (value === false) return 'Disattivo'
    if (typeof value === 'number') return formatNumber(value, 4)
    return String(value)
  }

  function renderWorldHighlights(settings) {
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
    elements.settingsGrid.replaceChildren()
    renderWorldHighlights(settings)
    if (!Object.keys(settings).length) {
      const empty = document.createElement('p')
      empty.className = 'empty-copy'
      empty.textContent = 'Configurazione non ancora ricevuta.'
      elements.settingsGrid.appendChild(empty)
      return
    }
    for (const [title, keys] of settingGroups) {
      const available = keys.filter((key) => Object.hasOwn(settings, key))
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
    }
  }

  function renderEvents(events) {
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

    if (state.selectedPlayer && !players.some((player) => player.id === state.selectedPlayer && hasMapLocation(player))) {
      clearSelection(false)
    }

    elements.headerStatus.classList.toggle('online', online)
    elements.headerStatus.classList.toggle('offline', !online)
    setText(elements.headerStatus.querySelector('b'), online ? 'ONLINE' : (stale ? 'DATI OBSOLETI' : 'OFFLINE'))
    setText(elements.serverName, data.info?.servername || 'Palworld Server')
    setText(elements.serverDescription, data.info?.description || 'Telemetria pubblica del server dedicato.')
    setText(elements.serverVersion, data.info?.version || '--')
    setText(elements.lastUpdate, formatDate(data.status?.last_updated))
    elements.lastUpdate.dateTime = data.status?.last_updated || ''
    setText(elements.heroPlayers, formatNumber(metrics.currentplayernum ?? players.length))
    setText(elements.heroCapacity, `/ ${formatNumber(metrics.maxplayernum)}`)
    setText(elements.heroFps, formatNumber(metrics.serverfps, 1))
    setText(elements.heroUptime, formatDuration(metrics.uptime))
    setText(elements.heroDay, formatNumber(metrics.days))
    const dataAge = data.status?.data_age_seconds
    setText(elements.signalAge, dataAge == null ? '--' : `${dataAge}s`)
    elements.signalBar.style.width = dataAge == null ? '0%' : `${Math.max(0, 100 - Math.min(100, dataAge / 1.2))}%`
    setText(elements.metricFpsAverage, formatNumber(data.summary_24h?.average_fps, 1))
    setText(elements.metricFpsMinimum, formatNumber(data.summary_24h?.minimum_fps, 1))
    setText(elements.metricFrameTime, formatNumber(metrics.serverframetime, 2))
    setText(elements.metricPeak, formatNumber(data.summary_24h?.peak_players))
    setText(elements.metricPlayersAverage, formatNumber(data.summary_24h?.average_players, 1))
    setText(elements.metricBases, formatNumber(metrics.basecampnum))

    renderMap(players)
    renderPlayersTable(players)
    renderSettings(data.settings || {})
    renderEvents(data.events || [])

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
    return {
      minFps,
      maxFps,
      maxPlayers: Math.max(1, observedMaxPlayers),
      observedMaxPlayers,
    }
  }

  function updateChartTooltip() {
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
    elements.chartTooltip.append(time, fps, players)
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
    const firstTime = new Date(validSamples[0].timestamp).getTime()
    const lastTime = new Date(validSamples[validSamples.length - 1].timestamp).getTime()
    const timeSpan = Math.max(1, lastTime - firstTime)
    const { minFps, maxFps, maxPlayers, observedMaxPlayers } = chartScale(validSamples)
    const observedMinFps = Math.min(...validSamples.map((sample) => Number(sample.fps) || 0))
    const observedMaxFps = Math.max(...validSamples.map((sample) => Number(sample.fps) || 0))
    setText(elements.chartSummary, `Storico di ${validSamples.length} campioni. FPS da ${formatNumber(observedMinFps, 1)} a ${formatNumber(observedMaxFps, 1)}; massimo ${formatNumber(observedMaxPlayers)} giocatori online.`)

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
      return {
        sample,
        x,
        yFps: pad.top + plotHeight - fpsRatio * plotHeight,
        yPlayers: pad.top + plotHeight - playerRatio * plotHeight,
      }
    })

    const drawLine = (field, color) => {
      context.beginPath()
      context.strokeStyle = color
      context.lineWidth = 2
      state.chartPoints.forEach((point, index) => {
        if (index === 0) context.moveTo(point.x, point[field])
        else context.lineTo(point.x, point[field])
      })
      context.stroke()
    }
    drawLine('yFps', '#4ce0c1')
    drawLine('yPlayers', '#ff735c')

    const compactLabels = width < 520
    const labels = [
      [formatChartDate(validSamples[0].timestamp, compactLabels, timeSpan), pad.left, 'left'],
      [formatChartDate(validSamples[validSamples.length - 1].timestamp, compactLabels, timeSpan), width - pad.right, 'right'],
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
      for (const [y, color] of [[hovered.yFps, '#4ce0c1'], [hovered.yPlayers, '#ff735c']]) {
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
    const requestedRange = elements.historyRange.value
    try {
      const data = await requestJson(`/api/v1/history?range=${encodeURIComponent(requestedRange)}`, 'history')
      if (requestedRange !== elements.historyRange.value) return
      state.historySamples = data.samples || []
      state.chartHoverIndex = null
      setNotice('history')
      setText(elements.chartEmpty, 'Lo storico inizierà a popolarsi con le trasmissioni del connector.')
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

  function showToast(message, error = false) {
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
      if (initial) showToast('Collegamento telemetrico stabilito')
      if (state.selectedPlayer) loadTrail(state.selectedPlayer)
    } catch (error) {
      if (error.name === 'AbortError') return
      if (initial) showToast('Dati temporaneamente non disponibili', true)
      elements.headerStatus.classList.remove('online')
      elements.headerStatus.classList.add('offline')
      setText(elements.headerStatus.querySelector('b'), 'CONNESSIONE PERSA')
      setNotice('snapshot', 'Collegamento telemetrico interrotto: i valori mostrati sono gli ultimi ricevuti.', true)
    }
  }

  function bindChartControls() {
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

  function bindMapControls() {
    $('#zoomIn').addEventListener('click', () => setZoom(state.map.scale + 0.45))
    $('#zoomOut').addEventListener('click', () => setZoom(state.map.scale - 0.45))
    $('#resetMap').addEventListener('click', resetMap)
    $('#clearSelection').addEventListener('click', () => clearSelection())
    $('#showFastTravel').addEventListener('change', (event) => elements.fastTravelLayer.classList.toggle('visible', event.target.checked))
    $('#showTowers').addEventListener('change', (event) => elements.towerLayer.classList.toggle('visible', event.target.checked))
    $('#showTrail').addEventListener('change', (event) => {
      if (!event.target.checked) clearTrail()
      else if (state.selectedPlayer) loadTrail(state.selectedPlayer)
    })

    elements.mapViewport.addEventListener('wheel', (event) => {
      const changed = setZoom(state.map.scale + (event.deltaY < 0 ? .3 : -.3))
      if (changed) event.preventDefault()
    }, { passive: false })
    elements.mapViewport.addEventListener('pointerdown', (event) => {
      if (event.target.closest('.map-marker.player')) return
      state.map.dragging = true
      state.map.pointerX = event.clientX
      state.map.pointerY = event.clientY
      elements.mapViewport.classList.add('dragging')
      elements.mapViewport.setPointerCapture(event.pointerId)
    })
    elements.mapViewport.addEventListener('pointermove', (event) => {
      const local = mapLocalFromPointer(event)
      const world = percentToWorld((local.x / local.width) * 100, (local.y / local.height) * 100)
      setText(elements.mapCoordinate, `X ${formatNumber(world.x, 0)} / Y ${formatNumber(world.y, 0)}`)
      if (!state.map.dragging) return
      state.map.panX += event.clientX - state.map.pointerX
      state.map.panY += event.clientY - state.map.pointerY
      state.map.pointerX = event.clientX
      state.map.pointerY = event.clientY
      applyMapTransform()
    })
    const stopDragging = () => {
      state.map.dragging = false
      elements.mapViewport.classList.remove('dragging')
    }
    elements.mapViewport.addEventListener('pointerup', stopDragging)
    elements.mapViewport.addEventListener('pointercancel', stopDragging)
    elements.mapViewport.addEventListener('dblclick', () => setZoom(state.map.scale + .5))
    elements.mapViewport.addEventListener('keydown', (event) => {
      const step = 36
      if (event.key === '+' || event.key === '=') setZoom(state.map.scale + .4)
      else if (event.key === '-') setZoom(state.map.scale - .4)
      else if (event.key === '0' || event.key === 'Home') resetMap()
      else if (event.key === 'ArrowLeft') state.map.panX += step
      else if (event.key === 'ArrowRight') state.map.panX -= step
      else if (event.key === 'ArrowUp') state.map.panY += step
      else if (event.key === 'ArrowDown') state.map.panY -= step
      else return
      event.preventDefault()
      applyMapTransform()
    })
  }

  async function loadStaticPoints() {
    try {
      state.points = await requestJson('/static/dashboard/data/map-points.json', 'points', 5000)
      renderStaticPoints()
    } catch (_error) {
      // Static POIs are optional; live player positions remain available.
    }
  }

  function scheduleHistoryPoll() {
    window.clearTimeout(state.historyTimer)
    state.historyTimer = window.setTimeout(async () => {
      await loadHistory()
      scheduleHistoryPoll()
    }, 60000)
  }

  async function snapshotLoop(initial = false) {
    await loadSnapshot(initial)
    window.setTimeout(() => snapshotLoop(false), 10000)
  }

  function initialize() {
    bindMapControls()
    bindChartControls()
    elements.historyRange.addEventListener('change', async () => {
      await loadHistory()
      scheduleHistoryPoll()
    })
    let resizeFrame = null
    window.addEventListener('resize', () => {
      window.cancelAnimationFrame(resizeFrame)
      resizeFrame = window.requestAnimationFrame(() => drawChart())
    })
    loadStaticPoints()
    snapshotLoop(true)
    loadHistory().then(scheduleHistoryPoll)
  }

  initialize()
})()
