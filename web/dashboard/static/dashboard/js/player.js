(() => {
  'use strict'

  const host = document.getElementById('playerPage')
  if (!host) return
  const publicId = host.dataset.playerPublicId || ''

  const elements = {
    content: document.getElementById('playerContent'),
    notFound: document.getElementById('playerNotFound'),
    status: document.getElementById('playerStatus'),
    name: document.getElementById('playerName'),
    meta: document.getElementById('playerMeta'),
    level: document.getElementById('plLevel'),
    buildings: document.getElementById('plBuildings'),
    playtime: document.getElementById('plPlaytime'),
    sessions: document.getElementById('plSessions'),
    longest: document.getElementById('plLongest'),
    firstSeen: document.getElementById('plFirstSeen'),
    lastSeen: document.getElementById('plLastSeen'),
    presenceGrid: document.getElementById('presenceGrid'),
    pingChart: document.getElementById('pingChart'),
    pingSummary: document.getElementById('pingSummary'),
    sessionList: document.getElementById('sessionList'),
    eventList: document.getElementById('playerEventList'),
  }

  const WEEKDAY_LABELS = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']

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

  function formatDuration(seconds) {
    if (seconds === null || seconds === undefined) return '--'
    let value = Math.max(0, Number(seconds) || 0)
    const days = Math.floor(value / 86400)
    value %= 86400
    const hours = Math.floor(value / 3600)
    value %= 3600
    const minutes = Math.floor(value / 60)
    if (days) return `${days}g ${hours}h`
    if (hours) return `${hours}h ${minutes}m`
    return `${minutes}m`
  }

  function formatDurationMinutes(minutes) {
    if (minutes === null || minutes === undefined) return '--'
    return formatDuration(Number(minutes) * 60)
  }

  function formatFullDate(value) {
    if (!value) return 'in corso'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '--'
    return new Intl.DateTimeFormat('it-IT', {
      day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    }).format(date)
  }

  function formatShortDate(value) {
    if (!value) return '--'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '--'
    return new Intl.DateTimeFormat('it-IT', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(date)
  }

  function renderProfile(player) {
    const online = Boolean(player.online)
    setText(elements.status, online ? 'Online ora' : 'Profilo esploratore')
    setText(elements.name, player.name)
    setText(elements.meta, online
      ? `In gioco da ${formatDuration(player.current_session)} · ${player.account_name || 'account non disponibile'}`
      : `${player.account_name || 'account non disponibile'} · ultimo accesso ${formatFullDate(player.last_seen)}`)
    setText(elements.level, formatNumber(player.level))
    setText(elements.buildings, formatNumber(player.building_count))
    setText(elements.playtime, formatDurationMinutes(player.minutes_lifetime))
    setText(elements.sessions, formatNumber(player.session_count_lifetime))
    setText(elements.longest, formatDurationMinutes(player.longest_session_minutes))
    setText(elements.firstSeen, formatFullDate(player.first_seen))
    setText(elements.lastSeen, formatFullDate(player.last_seen))
  }

  function renderPresence(presence) {
    if (!elements.presenceGrid) return
    const grid = Array.isArray(presence?.grid) ? presence.grid : []
    elements.presenceGrid.replaceChildren()
    const headerRow = document.createElement('tr')
    const corner = document.createElement('th')
    corner.scope = 'col'
    corner.className = 'sr-only'
    corner.textContent = 'Giorno'
    headerRow.appendChild(corner)
    for (let hour = 0; hour < 24; hour += 1) {
      const cell = document.createElement('th')
      cell.scope = 'col'
      cell.textContent = String(hour).padStart(2, '0')
      headerRow.appendChild(cell)
    }
    elements.presenceGrid.appendChild(headerRow)
    const maxMinutes = Math.max(1, ...grid.flat().map(Number))
    for (let day = 0; day < 7; day += 1) {
      const row = document.createElement('tr')
      const label = document.createElement('th')
      label.scope = 'row'
      label.textContent = WEEKDAY_LABELS[day]
      row.appendChild(label)
      const values = grid[day] || []
      for (let hour = 0; hour < 24; hour += 1) {
        const cell = document.createElement('td')
        const minutes = Number(values[hour]) || 0
        cell.textContent = minutes ? Math.round(minutes / 60 * 10) / 10 : ''
        cell.title = `${WEEKDAY_LABELS[day]} ${String(hour).padStart(2, '0')}:00 · ${minutes} min/settimana`
        if (minutes) {
          const intensity = Math.max(4, Math.round((minutes / maxMinutes) * 88))
          cell.style.setProperty('--heat', `${intensity}%`)
        } else {
          cell.className = 'zero'
        }
        row.appendChild(cell)
      }
      elements.presenceGrid.appendChild(row)
    }
  }

  function renderPing(samples) {
    if (!elements.pingChart) return
    const points = (Array.isArray(samples) ? samples : []).filter((sample) => Number.isFinite(new Date(sample.timestamp).getTime()))
    elements.pingChart.replaceChildren()
    if (points.length < 2) {
      const empty = document.createElement('p')
      empty.className = 'empty-copy'
      empty.textContent = 'Nessun campione di ping disponibile.'
      elements.pingChart.appendChild(empty)
      setText(elements.pingSummary, 'Nessun campione di ping disponibile.')
      return
    }
    const width = 800
    const height = 200
    const pad = { left: 14, right: 14, top: 12, bottom: 26 }
    const plotWidth = width - pad.left - pad.right
    const plotHeight = height - pad.top - pad.bottom
    const first = new Date(points[0].timestamp).getTime()
    const last = new Date(points[points.length - 1].timestamp).getTime()
    const timeSpan = Math.max(1, last - first)
    const pingValues = points.map((sample) => Number(sample.ping) || 0)
    const maxPing = Math.max(50, ...pingValues)
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`)
    svg.setAttribute('role', 'img')
    svg.setAttribute('aria-labelledby', 'pingSummary')
    const path = points.map((sample, index) => {
      const x = pad.left + ((new Date(sample.timestamp).getTime() - first) / timeSpan) * plotWidth
      const y = pad.top + plotHeight - ((Number(sample.ping) || 0) / maxPing) * plotHeight
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    }).join(' ')
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line')
    line.setAttribute('x1', pad.left)
    line.setAttribute('y1', pad.top + plotHeight)
    line.setAttribute('x2', width - pad.right)
    line.setAttribute('y2', pad.top + plotHeight)
    line.setAttribute('stroke', 'rgba(196,220,199,.13)')
    const polyline = document.createElementNS('http://www.w3.org/2000/svg', 'polyline')
    polyline.setAttribute('points', path)
    polyline.setAttribute('class', 'ping-line')
    const maxLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text')
    maxLabel.setAttribute('x', pad.left)
    maxLabel.setAttribute('y', pad.top + 4)
    maxLabel.setAttribute('class', 'axis-label')
    maxLabel.textContent = `${formatNumber(maxPing, 0)} ms`
    const firstLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text')
    firstLabel.setAttribute('x', pad.left)
    firstLabel.setAttribute('y', height - 6)
    firstLabel.setAttribute('class', 'axis-label')
    firstLabel.textContent = formatShortDate(points[0].timestamp)
    const lastLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text')
    lastLabel.setAttribute('x', width - pad.right)
    lastLabel.setAttribute('y', height - 6)
    lastLabel.setAttribute('text-anchor', 'end')
    lastLabel.setAttribute('class', 'axis-label')
    lastLabel.textContent = formatShortDate(points[points.length - 1].timestamp)
    svg.append(line, polyline, maxLabel, firstLabel, lastLabel)
    elements.pingChart.appendChild(svg)
    const maximum = Math.max(...pingValues)
    const average = pingValues.reduce((sum, value) => sum + value, 0) / pingValues.length
    setText(elements.pingSummary, `${points.length} campioni di ping: media ${formatNumber(average, 0)} ms, massimo ${formatNumber(maximum, 0)} ms.`)
  }

  function renderSessions(sessions) {
    if (!elements.sessionList) return
    const items = Array.isArray(sessions) ? sessions : []
    elements.sessionList.replaceChildren()
    if (!items.length) {
      const empty = document.createElement('li')
      empty.className = 'empty-copy'
      empty.textContent = 'Nessuna sessione registrata.'
      elements.sessionList.appendChild(empty)
      return
    }
    for (const session of items) {
      const item = document.createElement('li')
      const range = document.createElement('span')
      range.textContent = session.active
        ? `Dal ${formatFullDate(session.started_at)} · in corso`
        : `${formatShortDate(session.started_at)} → ${formatShortDate(session.ended_at)}`
      const duration = document.createElement('strong')
      duration.textContent = formatDurationMinutes(session.duration_minutes)
      item.append(range, duration)
      elements.sessionList.appendChild(item)
    }
  }

  function renderEvents(events) {
    if (!elements.eventList) return
    const items = Array.isArray(events) ? events : []
    elements.eventList.replaceChildren()
    if (!items.length) {
      const empty = document.createElement('li')
      empty.className = 'empty-copy'
      empty.textContent = 'Nessun evento registrato.'
      elements.eventList.appendChild(empty)
      return
    }
    for (const event of items) {
      const item = document.createElement('li')
      item.className = event.type
      const dot = document.createElement('i')
      const copy = document.createElement('span')
      copy.textContent = event.type === 'join' ? 'è entrato nel mondo' : 'ha lasciato il mondo'
      const time = document.createElement('time')
      time.dateTime = event.timestamp
      time.textContent = formatShortDate(event.timestamp)
      item.append(dot, copy, time)
      elements.eventList.appendChild(item)
    }
  }

  function render(data) {
    if (!data?.player) return
    renderProfile(data.player)
    renderPresence(data.presence)
    renderPing(data.ping)
    renderSessions(data.sessions)
    renderEvents(data.events)
    if (elements.content) elements.content.hidden = false
  }

  function showNotFound() {
    if (elements.notFound) elements.notFound.hidden = false
  }

  async function load() {
    if (!publicId) {
      showNotFound()
      return
    }
    let response
    try {
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), 10000)
      response = await fetch(`/api/v1/player/${encodeURIComponent(publicId)}`, {
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      })
      clearTimeout(timer)
    } catch (_error) {
      showNotFound()
      return
    }
    if (!response.ok) {
      showNotFound()
      return
    }
    try {
      render(await response.json())
    } catch (_error) {
      showNotFound()
    }
  }

  load()
})()
