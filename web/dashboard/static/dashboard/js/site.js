(() => {
  'use strict'

  const WORLD = {
    maxX: 349400,
    maxY: 724400,
    minX: -1099400,
    minY: -724400,
  }
  // Palette and interaction concepts adapted from RNZ01/palworld-server-dashboard.
  // This implementation uses deterministic public IDs; see THIRD_PARTY_NOTICES.txt.
  const PLAYER_COLORS = [
    '#22c55e', '#06b6d4', '#3b82f6', '#8b5cf6', '#ec4899', '#f43f5e',
    '#f97316', '#eab308', '#14b8a6', '#0ea5e9', '#6366f1', '#d946ef',
  ]
  const THEMES = new Set(['observatory', 'tron', 'ares', 'clu', 'athena', 'aphrodite', 'poseidon'])

  const state = {
    snapshot: null,
    selectedPlayer: null,
    map: { scale: 1, panX: 0, panY: 0, dragging: false, pointerX: 0, pointerY: 0, frame: null, renderTimer: null },
    points: { fast_travel: [], boss_tower: [] },
    historySamples: [],
    historyWindow: null,
    chartPoints: [],
    chartHoverIndex: null,
    requests: {},
    notices: { snapshot: null, history: null },
    snapshotTimer: null,
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
    mapViewport: $('#mapViewport'),
    mapPlane: $('#mapPlane'),
    mapImage: $('#mapImage'),
    mapImageError: $('#mapImageError'),
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
    mobilePlayers: $('#mobilePlayers'),
    playerArchive: $('#playerArchive'),
    playerArchiveStatus: $('#playerArchiveStatus'),
    playerSearch: $('#playerSearch'),
    favoritesOnly: $('#favoritesOnly'),
    settingsGrid: $('#settingsGrid'),
    settingsSearch: $('#settingsSearch'),
    serverProfile: $('#serverProfile'),
    worldHighlights: $('#worldHighlights'),
    eventList: $('#eventList'),
    historyRange: $('#historyRange'),
    historyChart: $('#historyChart'),
    chartEmpty: $('#chartEmpty'),
    chartSummary: $('#chartSummary'),
    chartTooltip: $('#chartTooltip'),
    performanceHealth: $('#performanceHealth'),
    healthLabel: $('#healthLabel'),
    healthScore: $('#healthScore'),
    healthDetail: $('#healthDetail'),
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

  function clampMapPan() {
    const rect = elements.mapViewport.getBoundingClientRect()
    const maxX = Math.max(0, (rect.width * (state.map.scale - 1)) / 2)
    const maxY = Math.max(0, (rect.height * (state.map.scale - 1)) / 2)
    state.map.panX = Math.max(-maxX, Math.min(maxX, state.map.panX))
    state.map.panY = Math.max(-maxY, Math.min(maxY, state.map.panY))
  }

  function applyMapTransform() {
    clampMapPan()
    if (state.map.frame !== null) return
    state.map.frame = window.requestAnimationFrame(() => {
      state.map.frame = null
      const { scale, panX, panY } = state.map
      elements.mapPlane.style.transform = `translate3d(${panX}px, ${panY}px, 0) scale(${scale})`
      elements.mapPlane.style.setProperty('--inverse-scale', String(1 / scale))
    })
  }

  function scheduleMapRender() {
    window.clearTimeout(state.map.renderTimer)
    state.map.renderTimer = window.setTimeout(() => {
      state.map.renderTimer = null
      if (state.snapshot) renderMap(state.snapshot.players || [])
    }, 120)
  }

  function setZoom(next, anchor = null) {
    const previous = state.map.scale
    const rect = elements.mapViewport.getBoundingClientRect()
    const centerX = rect.width / 2
    const centerY = rect.height / 2
    const anchorX = anchor?.x ?? centerX
    const anchorY = anchor?.y ?? centerY
    const localX = centerX + (anchorX - centerX - state.map.panX) / previous
    const localY = centerY + (anchorY - centerY - state.map.panY) / previous
    state.map.scale = Math.min(5, Math.max(1, next))
    if (state.map.scale === 1) {
      state.map.panX = 0
      state.map.panY = 0
    } else {
      state.map.panX = anchorX - centerX - state.map.scale * (localX - centerX)
      state.map.panY = anchorY - centerY - state.map.scale * (localY - centerY)
    }
    applyMapTransform()
    if (previous !== state.map.scale) scheduleMapRender()
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
    elements.trailLayer.style.setProperty('--trail-color', playerColor(player.id))
    applyMapTransform()
    renderMap(state.snapshot?.players || [])
    if ($('#showTrail').checked) loadTrail(player.id)
  }

  function marker(type, point, label = '') {
    const position = worldToPercent(point[0], point[1])
    const node = document.createElement(type === 'player' || type === 'cluster' ? 'button' : 'span')
    node.className = `map-marker ${type}`
    node.style.left = `${position.left}%`
    node.style.top = `${position.top}%`
    if (node instanceof HTMLButtonElement) node.type = 'button'
    const icon = document.createElement('span')
    node.appendChild(icon)
    if (label) {
      const caption = document.createElement('em')
      caption.textContent = label
      node.appendChild(caption)
    }
    return node
  }

  function groupMapPlayers(players) {
    const mapped = players
      .filter(hasMapLocation)
      .map((player) => ({ player, position: worldToPercent(player.location_x, player.location_y) }))
    if (state.map.scale >= 4.5 || mapped.length < 2) return mapped.map((entry) => [entry])
    const rect = elements.mapViewport.getBoundingClientRect()
    const threshold = 42
    const visited = new Set()
    const groups = []

    for (let index = 0; index < mapped.length; index += 1) {
      if (visited.has(index)) continue
      const queue = [index]
      const group = []
      visited.add(index)
      while (queue.length) {
        const currentIndex = queue.shift()
        const current = mapped[currentIndex]
        group.push(current)
        for (let candidateIndex = 0; candidateIndex < mapped.length; candidateIndex += 1) {
          if (visited.has(candidateIndex)) continue
          const candidate = mapped[candidateIndex]
          const distance = Math.hypot(
            ((candidate.position.left - current.position.left) / 100) * rect.width * state.map.scale,
            ((candidate.position.top - current.position.top) / 100) * rect.height * state.map.scale,
          )
          if (distance <= threshold) {
            visited.add(candidateIndex)
            queue.push(candidateIndex)
          }
        }
      }
      if (group.some((entry) => entry.player.id === state.selectedPlayer)) {
        groups.push(...group.map((entry) => [entry]))
      } else {
        groups.push(group)
      }
    }
    return groups
  }

  function centerPlayerGroup(group) {
    const x = group.reduce((total, entry) => total + Number(entry.player.location_x), 0) / group.length
    const y = group.reduce((total, entry) => total + Number(entry.player.location_y), 0) / group.length
    const position = worldToPercent(x, y)
    const rect = elements.mapViewport.getBoundingClientRect()
    state.map.scale = Math.min(5, Math.max(2.5, state.map.scale + 1.2))
    state.map.panX = ((50 - position.left) / 100) * rect.width * state.map.scale
    state.map.panY = ((50 - position.top) / 100) * rect.height * state.map.scale
    applyMapTransform()
    renderMap(state.snapshot?.players || [])
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

    for (const group of groupMapPlayers(players)) {
      if (group.length === 1) {
        const player = group[0].player
        const node = marker('player', [player.location_x, player.location_y], `Lv.${player.level} ${player.name}`)
        node.dataset.playerId = player.id
        node.style.setProperty('--player-color', playerColor(player.id))
        node.classList.toggle('selected', player.id === state.selectedPlayer)
        node.setAttribute('aria-label', `Centra ${player.name} sulla mappa`)
        node.setAttribute('aria-pressed', String(player.id === state.selectedPlayer))
        node.addEventListener('click', () => centerPlayer(player))
        elements.playerLayer.appendChild(node)
      } else {
        const x = group.reduce((total, entry) => total + Number(entry.player.location_x), 0) / group.length
        const y = group.reduce((total, entry) => total + Number(entry.player.location_y), 0) / group.length
        const names = group.map((entry) => entry.player.name).join(', ')
        const node = marker('cluster', [x, y], names)
        node.setAttribute('aria-label', `Avvicina ${group.length} giocatori: ${names}`)
        node.addEventListener('click', () => centerPlayerGroup(group))
        node.querySelector('span').textContent = String(group.length)
        elements.playerLayer.appendChild(node)
      }
    }

    for (const player of players) {
      const mapped = hasMapLocation(player)
      const roster = document.createElement('button')
      roster.type = 'button'
      roster.dataset.playerId = player.id
      roster.className = 'roster-player'
      roster.classList.toggle('selected', player.id === state.selectedPlayer)
      roster.classList.toggle('unmapped', !mapped)
      roster.setAttribute('aria-pressed', String(player.id === state.selectedPlayer))
      roster.style.setProperty('--player-color', playerColor(player.id))
      if (!mapped) roster.disabled = true
      const avatar = document.createElement('i')
      avatar.textContent = initials(player.name)
      const color = playerColor(player.id)
      avatar.style.backgroundColor = color
      avatar.style.color = contrastColor(color)
      const identity = document.createElement('span')
      const name = document.createElement('strong')
      name.textContent = player.name
      const detail = document.createElement('small')
      detail.textContent = `Lv.${player.level} · ${formatNumber(player.ping, 0)} ms`
      detail.className = pingClass(player.ping)
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
      const range = $('#trailRange').value
      const data = await requestJson(`/api/v1/player/${encodeURIComponent(playerId)}/trail?range=${encodeURIComponent(range)}`, 'trail')
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
      playerButton.style.setProperty('--player-color', playerColor(player.id))
      const name = document.createElement('strong')
      name.textContent = player.name
      const account = document.createElement('small')
      account.textContent = player.accountName || 'account non disponibile'
      playerButton.append(name, account)
      if (mapped) {
        playerButton.setAttribute('aria-label', `Mostra ${player.name} sulla mappa`)
        playerButton.addEventListener('click', () => centerPlayer(player))
      } else {
        playerButton.disabled = true
      }
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
    elements.mobilePlayers.replaceChildren()
    if (!players.length) {
      const empty = document.createElement('p')
      empty.className = 'empty-copy'
      empty.textContent = 'Nessun giocatore online.'
      elements.mobilePlayers.appendChild(empty)
      return
    }
    for (const player of players) {
      const mapped = hasMapLocation(player)
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
      card.append(avatar, identity, ping, stats)
      if (mapped) {
        const locate = document.createElement('button')
        locate.type = 'button'
        locate.textContent = 'Mostra sulla mappa'
        locate.addEventListener('click', () => centerPlayer(player))
        card.appendChild(locate)
      }
      elements.mobilePlayers.appendChild(card)
    }
  }

  function renderPlayerArchive(players) {
    const expanded = new Set(
      [...elements.playerArchive.querySelectorAll('details[open]')]
        .map((details) => details.closest('[data-player-id]')?.dataset.playerId),
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
      account.textContent = player.accountName || 'account non disponibile'
      identity.append(name, account)
      const status = document.createElement('span')
      status.className = player.online ? 'archive-status online' : 'archive-status'
      status.textContent = player.online ? 'Online ora' : `Ultimo accesso ${formatFullDate(player.last_seen)}`
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
      header.append(avatar, identity, status, favorite)

      const totals = document.createElement('dl')
      totals.className = 'player-time-grid'
      for (const [label, value] of [
        ['Ultimi 30 giorni', player.minutes_30d],
        ['Ultimi 365 giorni', player.minutes_365d],
        ['Da sempre', player.minutes_all],
      ]) {
        const item = document.createElement('div')
        const term = document.createElement('dt')
        term.textContent = label
        const description = document.createElement('dd')
        description.textContent = `${formatNumber(value)} min`
        item.append(term, description)
        totals.appendChild(item)
      }

      const meta = document.createElement('p')
      meta.className = 'player-history-meta'
      const sessionLabel = Number(player.session_count) === 1 ? 'sessione' : 'sessioni'
      meta.textContent = `Prima visita ${formatFullDate(player.first_seen)} · ${formatNumber(player.session_count)} ${sessionLabel}`
      card.append(header, totals, meta)

      if (player.periods?.length) {
        const details = document.createElement('details')
        details.open = expanded.has(player.id)
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
    setText(elements.serverDescription, data.info?.description || 'Telemetria riservata del server dedicato.')
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
    renderMobilePlayers(players)
    renderServerProfile(data)
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

  function renderFpsHealth(health = {}) {
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
    const firstTime = Number.isFinite(new Date(state.historyWindow?.from).getTime())
      ? new Date(state.historyWindow.from).getTime()
      : new Date(validSamples[0].timestamp).getTime()
    const lastTime = Number.isFinite(new Date(state.historyWindow?.to).getTime())
      ? new Date(state.historyWindow.to).getTime()
      : new Date(validSamples[validSamples.length - 1].timestamp).getTime()
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
    drawLine('yFps', fpsColor)
    drawLine('yPlayers', playersColor)

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
      for (const [y, color] of [[hovered.yFps, fpsColor], [hovered.yPlayers, playersColor]]) {
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
      state.historyWindow = data.window || null
      state.chartHoverIndex = null
      renderFpsHealth(data.fps_health)
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
      return true
    } catch (error) {
      if (error.name === 'AbortError') return null
      if (initial) showToast('Dati temporaneamente non disponibili', true)
      elements.headerStatus.classList.remove('online')
      elements.headerStatus.classList.add('offline')
      setText(elements.headerStatus.querySelector('b'), 'CONNESSIONE PERSA')
      setNotice('snapshot', 'Collegamento telemetrico interrotto: i valori mostrati sono gli ultimi ricevuti.', true)
      return false
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

  function bindMapControls() {
    const layerPreferences = [
      ['showPlayers', elements.playerLayer, 'players', true],
      ['showFastTravel', elements.fastTravelLayer, 'fastTravel', false],
      ['showTowers', elements.towerLayer, 'towers', false],
    ]
    for (const [inputId, layer, key, defaultVisible] of layerPreferences) {
      const input = $(`#${inputId}`)
      input.checked = readStorage(`observatory.map.${key}`, defaultVisible ? '1' : '0') === '1'
      if (key === 'players') layer.hidden = !input.checked
      else layer.classList.toggle('visible', input.checked)
      input.addEventListener('change', (event) => {
        if (key === 'players') layer.hidden = !event.target.checked
        else layer.classList.toggle('visible', event.target.checked)
        writeStorage(`observatory.map.${key}`, event.target.checked ? '1' : '0')
      })
    }
    const trailToggle = $('#showTrail')
    trailToggle.checked = readStorage('observatory.map.trail', '1') !== '0'
    const storedTrailRange = readStorage('observatory.map.trailRange', '6h')
    $('#trailRange').value = ['1h', '6h', '24h', '7d'].includes(storedTrailRange) ? storedTrailRange : '6h'
    $('#zoomIn').addEventListener('click', () => setZoom(state.map.scale + 0.45))
    $('#zoomOut').addEventListener('click', () => setZoom(state.map.scale - 0.45))
    $('#resetMap').addEventListener('click', resetMap)
    $('#clearSelection').addEventListener('click', () => clearSelection())
    trailToggle.addEventListener('change', (event) => {
      writeStorage('observatory.map.trail', event.target.checked ? '1' : '0')
      if (!event.target.checked) clearTrail()
      else if (state.selectedPlayer) loadTrail(state.selectedPlayer)
    })
    $('#trailRange').addEventListener('change', (event) => {
      writeStorage('observatory.map.trailRange', event.target.value)
      if (state.selectedPlayer && trailToggle.checked) loadTrail(state.selectedPlayer)
    })

    elements.mapViewport.addEventListener('wheel', (event) => {
      const rect = elements.mapViewport.getBoundingClientRect()
      const changed = setZoom(
        state.map.scale + (event.deltaY < 0 ? .3 : -.3),
        { x: event.clientX - rect.left, y: event.clientY - rect.top },
      )
      if (changed) event.preventDefault()
    }, { passive: false })
    elements.mapViewport.addEventListener('pointerdown', (event) => {
      if (event.target.closest('.map-marker')) return
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
    elements.mapViewport.addEventListener('dblclick', (event) => {
      const rect = elements.mapViewport.getBoundingClientRect()
      setZoom(state.map.scale + .5, { x: event.clientX - rect.left, y: event.clientY - rect.top })
    })
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
    try {
      const favorites = JSON.parse(readStorage('observatory.favoritePlayers', '[]'))
      if (Array.isArray(favorites)) state.favoritePlayers = new Set(favorites.filter((value) => typeof value === 'string'))
    } catch (_error) {
      state.favoritePlayers = new Set()
    }
    bindMapControls()
    bindChartControls()
    bindCredentialControls()
    elements.themeSelect.addEventListener('change', (event) => {
      const theme = THEMES.has(event.target.value) ? event.target.value : 'observatory'
      document.documentElement.dataset.theme = theme
      writeStorage('observatory.theme', theme)
      drawChart()
    })
    elements.playerSearch.addEventListener('input', (event) => {
      state.playerQuery = event.target.value
      renderPlayerArchive(state.archivePlayers)
    })
    elements.favoritesOnly.addEventListener('change', (event) => {
      state.favoritesOnly = event.target.checked
      renderPlayerArchive(state.archivePlayers)
    })
    elements.settingsSearch.addEventListener('input', () => renderSettings(state.snapshot?.settings || {}))
    elements.historyRange.addEventListener('change', async () => {
      await loadHistory()
      scheduleHistoryPoll()
    })
    const setMapImageState = (failed) => {
      elements.mapImageError.hidden = !failed
    }
    elements.mapImage.addEventListener('load', () => setMapImageState(false))
    elements.mapImage.addEventListener('error', () => setMapImageState(true))
    if (elements.mapImage.complete) setMapImageState(elements.mapImage.naturalWidth === 0)
    let resizeFrame = null
    window.addEventListener('resize', () => {
      window.cancelAnimationFrame(resizeFrame)
      resizeFrame = window.requestAnimationFrame(() => {
        applyMapTransform()
        if (state.snapshot) renderMap(state.snapshot.players || [])
        drawChart()
      })
    })
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) return
      snapshotLoop(false)
      loadHistory().then(scheduleHistoryPoll)
      loadPlayerArchive().then(scheduleArchivePoll)
    })
    loadStaticPoints()
    snapshotLoop(true)
    loadHistory().then(scheduleHistoryPoll)
    loadPlayerArchive().then(scheduleArchivePoll)
  }

  initialize()
})()
