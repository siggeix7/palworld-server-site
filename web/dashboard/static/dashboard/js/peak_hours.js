(() => {
  'use strict'

  const THEMES = new Set(['observatory', 'tron', 'ares', 'clu', 'athena', 'aphrodite', 'poseidon'])
  const WEEKDAY_LABELS = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']

  const state = {
    range: '30d',
    data: null,
    requests: {},
    pollTimer: null,
    pollGeneration: 0,
    hover: null,
    resizeFrame: null,
  }

  const $ = (selector) => document.querySelector(selector)
  const elements = {
    range: $('#peakRange'),
    canvas: $('#peakHeatmap'),
    summary: $('#peakSummary'),
    empty: $('#peakEmpty'),
    notice: $('#peakNotice'),
    peakHour: $('#peakHour'),
    peakDay: $('#peakDay'),
    peakSessions: $('#peakSessions'),
    peakTotal: $('#peakTotal'),
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

  function formatDuration(minutes) {
    const value = Number(minutes) || 0
    if (value <= 0) return '--'
    const days = Math.floor(value / 1440)
    const hours = Math.floor((value % 1440) / 60)
    const mins = Math.floor(value % 60)
    if (days) return `${days}g ${hours}h`
    if (hours) return `${hours}h ${mins}m`
    return `${mins}m`
  }

  function setNotice(message = '', error = false) {
    if (!elements.notice) return
    setText(elements.notice, message)
    elements.notice.hidden = !message
    elements.notice.classList.toggle('error', error)
  }

  async function requestJson(url, key, timeout = 10000) {
    state.requests[key]?.abort()
    const controller = new AbortController()
    state.requests[key] = controller
    let timedOut = false
    const timer = window.setTimeout(() => { timedOut = true; controller.abort() }, timeout)
    try {
      const response = await fetch(url, { cache: 'no-store', credentials: 'same-origin', headers: { Accept: 'application/json' }, signal: controller.signal })
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

  function renderStats(data) {
    const peakHour = data.peak_hour == null ? '--' : `${String(data.peak_hour).padStart(2, '0')}:00`
    setText(elements.peakHour, peakHour)
    setText(elements.peakDay, data.peak_day || '--')
    setText(elements.peakSessions, formatNumber(data.session_count))
    setText(elements.peakTotal, formatDuration(data.total_minutes))
  }

  function drawHeatmap() {
    const canvas = elements.canvas
    if (!canvas) return
    const context = canvas.getContext('2d')
    const rect = canvas.getBoundingClientRect()
    const width = Math.max(1, rect.width)
    const height = Math.max(1, rect.height)
    const ratio = Math.min(2, window.devicePixelRatio || 1)
    canvas.width = Math.floor(width * ratio)
    canvas.height = Math.floor(height * ratio)
    context.setTransform(ratio, 0, 0, ratio, 0, 0)
    context.clearRect(0, 0, width, height)

    const grid = state.data?.grid
    const hasData = Array.isArray(grid) && grid.some((row) => row.some((value) => value > 0))
    elements.empty.hidden = hasData
    if (!hasData) {
      setText(elements.summary, 'Nessun dato di attività nel periodo selezionato.')
      return
    }

    const maxVal = Math.max(...grid.flat())
    const pad = { left: 44, right: 12, top: 12, bottom: 28 }
    const cols = 24
    const rows = 7
    const plotW = Math.max(1, width - pad.left - pad.right)
    const plotH = Math.max(1, height - pad.top - pad.bottom)
    const cellW = plotW / cols
    const cellH = plotH / rows
    const styles = getComputedStyle(document.documentElement)
    const teal = styles.getPropertyValue('--teal').trim() || '#4ce0c1'

    function heatColor(value) {
      if (value <= 0) return 'rgba(196,220,199,0.06)'
      const ratio = Math.min(1, value / maxVal)
      const alpha = 0.15 + ratio * 0.85
      const hex = teal.replace('#', '')
      const r = parseInt(hex.slice(0, 2), 16)
      const g = parseInt(hex.slice(2, 4), 16)
      const b = parseInt(hex.slice(4, 6), 16)
      return `rgba(${r},${g},${b},${alpha.toFixed(3)})`
    }

    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) {
        const value = grid[row][col] || 0
        context.fillStyle = heatColor(value)
        context.fillRect(pad.left + col * cellW + 1, pad.top + row * cellH + 1, cellW - 2, cellH - 2)
      }
    }

    context.fillStyle = '#8ea29a'
    context.font = '11px ui-monospace, monospace'
    context.textAlign = 'right'
    for (let row = 0; row < rows; row += 1) {
      context.fillText(WEEKDAY_LABELS[row], pad.left - 6, pad.top + row * cellH + cellH / 2 + 4)
    }
    context.textAlign = 'center'
    for (let col = 0; col < cols; col += 2) {
      context.fillText(String(col).padStart(2, '0'), pad.left + col * cellW + cellW / 2, height - 8)
    }
    context.textAlign = 'left'

    if (state.hover) {
      const { row, col } = state.hover
      const value = grid[row][col] || 0
      context.strokeStyle = 'rgba(233,224,197,0.5)'
      context.lineWidth = 2
      context.strokeRect(pad.left + col * cellW + 1, pad.top + row * cellH + 1, cellW - 2, cellH - 2)
      setText(elements.summary, `${WEEKDAY_LABELS[row]} ore ${String(col).padStart(2, '0')}:00 · ${formatNumber(value, 0)} minuti`)
    } else {
      setText(elements.summary, `Attività su ${state.data.session_count} sessioni. Picco: ${state.data.peak_day || '--'} alle ${state.data.peak_hour == null ? '--' : String(state.data.peak_hour).padStart(2, '0') + ':00'}.`)
    }
  }

  async function load() {
    const range = elements.range?.value || state.range
    state.range = range
    try {
      const data = await requestJson(`/api/v1/activity/heatmap?range=${encodeURIComponent(range)}`, 'heatmap')
      if (range !== state.range) return
      state.data = data
      renderStats(data)
      setNotice()
      drawHeatmap()
    } catch (error) {
      if (error.name === 'AbortError') return
      setNotice('Attività temporaneamente non disponibile.', true)
    }
  }

  function startPolling() {
    window.clearTimeout(state.pollTimer)
    const generation = ++state.pollGeneration
    const tick = async () => {
      if (document.hidden || generation !== state.pollGeneration) return
      await load()
      if (generation !== state.pollGeneration) return
      state.pollTimer = window.setTimeout(tick, 120000)
    }
    tick()
  }

  function initializeTheme() {
    try {
      const stored = window.localStorage.getItem('observatory.theme') || 'observatory'
      document.documentElement.dataset.theme = THEMES.has(stored) ? stored : 'observatory'
    } catch (_error) {
      document.documentElement.dataset.theme = 'observatory'
    }
  }

  function initialize() {
    initializeTheme()
    if (elements.range) {
      elements.range.addEventListener('change', load)
    }
    if (elements.canvas) {
      elements.canvas.addEventListener('pointermove', (event) => {
        if (!state.data?.grid) return
        const rect = elements.canvas.getBoundingClientRect()
        const x = event.clientX - rect.left
        const y = event.clientY - rect.top
        const pad = { left: 44, right: 12, top: 12, bottom: 28 }
        const cols = 24
        const rows = 7
        const plotW = rect.width - pad.left - pad.right
        const plotH = rect.height - pad.top - pad.bottom
        const col = Math.floor((x - pad.left) / (plotW / cols))
        const row = Math.floor((y - pad.top) / (plotH / rows))
        if (col < 0 || col >= cols || row < 0 || row >= rows) {
          if (state.hover) { state.hover = null; drawHeatmap() }
          return
        }
        if (!state.hover || state.hover.row !== row || state.hover.col !== col) {
          state.hover = { row, col }
          drawHeatmap()
        }
      })
      elements.canvas.addEventListener('pointerleave', () => {
        if (state.hover) { state.hover = null; drawHeatmap() }
      })
    }
    window.addEventListener('resize', () => {
      window.cancelAnimationFrame(state.resizeFrame)
      state.resizeFrame = window.requestAnimationFrame(drawHeatmap)
    })
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) return
      startPolling()
    })
    startPolling()
  }

  initialize()
})()
