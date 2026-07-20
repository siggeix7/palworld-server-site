(() => {
  'use strict'

  const WORLD = {
    maxX: 447900,
    maxY: 708920,
    minX: -999940,
    minY: -738920,
  }

  const state = {
    snapshot: null,
    selectedPlayer: null,
    map: { scale: 1, panX: 0, panY: 0, dragging: false, pointerX: 0, pointerY: 0 },
    points: { fast_travel: [], boss_tower: [] },
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
    metricFrameTime: $('#metricFrameTime'),
    metricPeak: $('#metricPeak'),
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
    playersTable: $('#playersTable'),
    settingsGrid: $('#settingsGrid'),
    eventList: $('#eventList'),
    historyRange: $('#historyRange'),
    historyChart: $('#historyChart'),
    chartEmpty: $('#chartEmpty'),
    chartSummary: $('#chartSummary'),
    connectionToast: $('#connectionToast'),
  }

  function setText(element, value) {
    if (element) element.textContent = value
  }

  function formatNumber(value, digits = 0) {
    const number = Number(value)
    if (!Number.isFinite(number)) return '--'
    return number.toLocaleString('it-IT', { maximumFractionDigits: digits })
  }

  function formatDuration(value) {
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

  function initials(name) {
    return String(name || '?').split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase()
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
    state.map.scale = Math.min(5, Math.max(1, next))
    if (state.map.scale === 1) {
      state.map.panX = 0
      state.map.panY = 0
    }
    applyMapTransform()
  }

  function resetMap() {
    state.map.scale = 1
    state.map.panX = 0
    state.map.panY = 0
    state.selectedPlayer = null
    elements.trailLayer.querySelector('polyline').setAttribute('points', '')
    applyMapTransform()
  }

  function centerPlayer(player) {
    const position = worldToPercent(player.location_x, player.location_y)
    const rect = elements.mapViewport.getBoundingClientRect()
    state.map.scale = Math.max(2.2, state.map.scale)
    state.map.panX = (50 - position.left) / 100 * rect.width * state.map.scale
    state.map.panY = (50 - position.top) / 100 * rect.height * state.map.scale
    state.selectedPlayer = player.id
    applyMapTransform()
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

  function renderMap(players) {
    elements.playerLayer.replaceChildren()
    elements.mapRoster.replaceChildren()
    setText(elements.rosterCount, String(players.length))
    elements.mapEmpty.classList.toggle('visible', players.length === 0)

    if (!players.length) {
      const empty = document.createElement('p')
      empty.className = 'empty-copy'
      empty.textContent = 'Nessun esploratore rilevato.'
      elements.mapRoster.appendChild(empty)
      elements.trailLayer.querySelector('polyline').setAttribute('points', '')
      return
    }

    for (const player of players) {
      const node = marker('player', [player.location_x, player.location_y], `Lv.${player.level} ${player.name}`)
      node.setAttribute('aria-label', `Centra ${player.name} sulla mappa`)
      node.addEventListener('click', () => centerPlayer(player))
      elements.playerLayer.appendChild(node)

      const roster = document.createElement('button')
      roster.type = 'button'
      roster.className = 'roster-player'
      const avatar = document.createElement('i')
      avatar.textContent = initials(player.name)
      const identity = document.createElement('span')
      const name = document.createElement('strong')
      name.textContent = player.name
      const detail = document.createElement('small')
      detail.textContent = `Lv.${player.level} · ${formatNumber(player.ping, 0)} ms`
      identity.append(name, detail)
      const coordinate = document.createElement('span')
      coordinate.textContent = `${formatNumber(player.location_x, 0)} / ${formatNumber(player.location_y, 0)}`
      roster.append(avatar, identity, coordinate)
      roster.addEventListener('click', () => centerPlayer(player))
      elements.mapRoster.appendChild(roster)
    }
  }

  async function loadTrail(playerId) {
    if (!playerId || !$('#showTrail').checked) {
      elements.trailLayer.querySelector('polyline').setAttribute('points', '')
      return
    }
    try {
      const response = await fetch(`/api/v1/player/${encodeURIComponent(playerId)}/trail?range=6h`, { cache: 'no-store' })
      if (!response.ok) throw new Error('trail unavailable')
      const data = await response.json()
      if (state.selectedPlayer !== playerId) return
      const points = data.positions.map((position) => {
        const mapped = worldToPercent(position.x, position.y)
        return `${mapped.left * 10},${mapped.top * 10}`
      }).join(' ')
      elements.trailLayer.querySelector('polyline').setAttribute('points', points)
    } catch (_error) {
      elements.trailLayer.querySelector('polyline').setAttribute('points', '')
    }
  }

  function renderPlayersTable(players) {
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
      const row = document.createElement('tr')
      const identity = document.createElement('td')
      const name = document.createElement('strong')
      name.textContent = player.name
      const account = document.createElement('small')
      account.textContent = player.accountName || 'account non disponibile'
      identity.append(name, account)

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
      code.textContent = `X ${formatNumber(player.location_x, 0)} · Y ${formatNumber(player.location_y, 0)}`
      coords.appendChild(code)
      row.append(identity, level, ping, buildings, session, coords)
      row.addEventListener('click', () => centerPlayer(player))
      elements.playersTable.appendChild(row)
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

  function renderSettings(settings) {
    elements.settingsGrid.replaceChildren()
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

    elements.headerStatus.classList.toggle('online', online)
    elements.headerStatus.classList.toggle('offline', !online)
    setText(elements.headerStatus.querySelector('b'), online ? 'ONLINE' : (data.status?.stale ? 'DATI OBSOLETI' : 'OFFLINE'))
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
    setText(elements.signalAge, data.status?.data_age_seconds == null ? '--' : `${data.status.data_age_seconds}s`)
    elements.signalBar.style.width = `${Math.max(0, 100 - Math.min(100, (data.status?.data_age_seconds || 0) / 1.2))}%`
    setText(elements.metricFpsAverage, formatNumber(data.summary_24h?.average_fps, 1))
    setText(elements.metricFrameTime, formatNumber(metrics.serverframetime, 2))
    setText(elements.metricPeak, formatNumber(data.summary_24h?.peak_players))
    setText(elements.metricBases, formatNumber(metrics.basecampnum))

    renderMap(players)
    renderPlayersTable(players)
    renderSettings(data.settings || {})
    renderEvents(data.events || [])

    if (state.selectedPlayer && !players.some((player) => player.id === state.selectedPlayer)) {
      state.selectedPlayer = null
      elements.trailLayer.querySelector('polyline').setAttribute('points', '')
    }
  }

  function drawChart(samples) {
    const canvas = elements.historyChart
    const context = canvas.getContext('2d')
    const rect = canvas.getBoundingClientRect()
    const ratio = window.devicePixelRatio || 1
    canvas.width = Math.max(1, Math.floor(rect.width * ratio))
    canvas.height = Math.max(1, Math.floor(300 * ratio))
    context.scale(ratio, ratio)
    context.clearRect(0, 0, rect.width, 300)
    elements.chartEmpty.hidden = samples.length > 1
    if (samples.length < 2) {
      setText(elements.chartSummary, 'Nessun campione storico disponibile.')
      return
    }

    const width = rect.width
    const height = 300
    const pad = { left: 42, right: 28, top: 20, bottom: 30 }
    const plotWidth = width - pad.left - pad.right
    const plotHeight = height - pad.top - pad.bottom
    const maxFps = Math.max(60, ...samples.map((sample) => Number(sample.fps) || 0))
    const maxPlayers = Math.max(1, ...samples.map((sample) => Number(sample.max_players) || Number(sample.players) || 0))
    const minFps = Math.min(...samples.map((sample) => Number(sample.fps) || 0))
    setText(elements.chartSummary, `Storico composto da ${samples.length} campioni. FPS da ${formatNumber(minFps, 1)} a ${formatNumber(maxFps, 1)}; massimo ${formatNumber(maxPlayers)} giocatori.`)

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
      context.fillText(String(Math.round(maxFps * (1 - index / 4))), 6, y + 4)
    }

    const draw = (field, color, max) => {
      context.beginPath()
      context.strokeStyle = color
      context.lineWidth = 2
      samples.forEach((sample, index) => {
        const x = pad.left + (index / (samples.length - 1)) * plotWidth
        const y = pad.top + plotHeight - ((Number(sample[field]) || 0) / max) * plotHeight
        if (index === 0) context.moveTo(x, y)
        else context.lineTo(x, y)
      })
      context.stroke()
    }
    draw('fps', '#4ce0c1', maxFps)
    draw('players', '#ff735c', maxPlayers)

    const first = formatDate(samples[0].timestamp, true)
    const last = formatDate(samples[samples.length - 1].timestamp, true)
    context.fillStyle = '#8ea29a'
    context.fillText(first, pad.left, height - 7)
    const measured = context.measureText(last).width
    context.fillText(last, width - pad.right - measured, height - 7)
  }

  async function loadHistory() {
    try {
      const response = await fetch(`/api/v1/history?range=${encodeURIComponent(elements.historyRange.value)}`, { cache: 'no-store' })
      if (!response.ok) throw new Error('history unavailable')
      const data = await response.json()
      drawChart(data.samples || [])
    } catch (_error) {
      drawChart([])
    }
  }

  function showToast(message, error = false) {
    setText(elements.connectionToast, message)
    elements.connectionToast.classList.toggle('error', error)
    elements.connectionToast.classList.add('visible')
    window.setTimeout(() => elements.connectionToast.classList.remove('visible'), 3500)
  }

  async function loadSnapshot(initial = false) {
    try {
      const response = await fetch('/api/v1/snapshot', { cache: 'no-store' })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json()
      renderSnapshot(data)
      if (initial) showToast('Collegamento telemetrico stabilito')
    } catch (_error) {
      if (initial) showToast('Dati temporaneamente non disponibili', true)
      elements.headerStatus.classList.remove('online')
      elements.headerStatus.classList.add('offline')
      setText(elements.headerStatus.querySelector('b'), 'CONNESSIONE PERSA')
    }
  }

  function bindMapControls() {
    $('#zoomIn').addEventListener('click', () => setZoom(state.map.scale + 0.45))
    $('#zoomOut').addEventListener('click', () => setZoom(state.map.scale - 0.45))
    $('#resetMap').addEventListener('click', resetMap)
    $('#showFastTravel').addEventListener('change', (event) => elements.fastTravelLayer.classList.toggle('visible', event.target.checked))
    $('#showTowers').addEventListener('change', (event) => elements.towerLayer.classList.toggle('visible', event.target.checked))
    $('#showTrail').addEventListener('change', (event) => {
      if (!event.target.checked) elements.trailLayer.querySelector('polyline').setAttribute('points', '')
      else if (state.selectedPlayer) loadTrail(state.selectedPlayer)
    })

    elements.mapViewport.addEventListener('wheel', (event) => {
      event.preventDefault()
      setZoom(state.map.scale + (event.deltaY < 0 ? .3 : -.3))
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

  async function initialize() {
    bindMapControls()
    elements.historyRange.addEventListener('change', loadHistory)
    window.addEventListener('resize', () => loadHistory())
    try {
      const response = await fetch('/static/dashboard/data/map-points.json')
      if (response.ok) state.points = await response.json()
      renderStaticPoints()
    } catch (_error) {
      // Static POIs are optional; live player positions remain available.
    }
    await Promise.all([loadSnapshot(true), loadHistory()])
    window.setInterval(() => loadSnapshot(false), 10000)
    window.setInterval(loadHistory, 60000)
  }

  initialize()
})()
