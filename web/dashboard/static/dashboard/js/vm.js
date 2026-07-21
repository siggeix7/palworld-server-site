(() => {
  'use strict'

  const VM_KEYS = [
    'cpu.util_pct',
    'memory.util_pct',
    'memory.available_bytes',
    'load.1m',
    'load.5m',
    'load.15m',
    'uptime_seconds',
    'filesystem.root.util_pct',
    'network.rx_bps',
    'network.tx_bps',
    'docker.ping',
    'docker.containers.total',
    'docker.containers.running',
    'docker.containers.stopped',
    'docker.containers.paused',
    'docker.cpu_pct_sum',
    'docker.memory_active_bytes',
  ]
  const THEMES = new Set(['observatory', 'tron', 'ares', 'clu', 'athena', 'aphrodite', 'poseidon'])
  const POLL_INTERVAL = 30000

  const state = {
    history: { cpu: [], memory: [], window: null },
    requests: {},
    snapshot: null,
    pollTimer: null,
    pollGeneration: 0,
    resizeFrame: null,
  }

  const $ = (selector) => document.querySelector(selector)
  const elements = {
    healthBanner: $('#vmHealthBanner'),
    healthTitle: $('#vmHealthTitle'),
    healthDetail: $('#vmHealthDetail'),
    lastUpdated: $('#vmLastUpdated'),
    emptyState: $('#vmEmptyState'),
    telemetryContent: $('#vmTelemetryContent'),
    historyRange: $('#vmHistoryRange'),
    historyChart: $('#vmHistoryChart'),
    chartSummary: $('#vmChartSummary'),
    chartEmpty: $('#vmChartEmpty'),
    historyNotice: $('#vmHistoryNotice'),
    connectorSection: $('#connectorDiagnostics'),
    connectorNotice: $('#connectorNotice'),
    connectorDatasets: $('#connectorDatasets'),
    connectorMissing: $('#connectorMissing'),
    connectorBatchesTable: $('#connectorBatchesTable'),
  }

  function setText(element, value) {
    if (!element) return
    const text = String(value)
    if (element.textContent !== text) element.textContent = text
  }

  function setTextById(id, value) {
    setText(document.getElementById(id), value)
  }

  function finiteNumber(value) {
    if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null
    const number = Number(value)
    return Number.isFinite(number) ? number : null
  }

  function formatNumber(value, digits = 0) {
    const number = finiteNumber(value)
    if (number === null) return '--'
    return number.toLocaleString('it-IT', { maximumFractionDigits: digits })
  }

  function formatPercent(value) {
    const number = finiteNumber(value)
    return number === null ? '--' : `${formatNumber(number, 1)}%`
  }

  function formatBytes(value) {
    const number = finiteNumber(value)
    if (number === null || number < 0) return '--'
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
    let amount = number
    let unit = 0
    while (amount >= 1024 && unit < units.length - 1) {
      amount /= 1024
      unit += 1
    }
    return `${formatNumber(amount, amount < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`
  }

  function formatRate(value) {
    const number = finiteNumber(value)
    if (number === null || number < 0) return '--'
    const units = ['bit/s', 'kbit/s', 'Mbit/s', 'Gbit/s', 'Tbit/s']
    let amount = number
    let unit = 0
    while (amount >= 1000 && unit < units.length - 1) {
      amount /= 1000
      unit += 1
    }
    return `${formatNumber(amount, amount < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`
  }

  function formatDuration(value) {
    const numeric = finiteNumber(value)
    if (numeric === null) return '--'
    let seconds = Math.max(0, Math.round(numeric))
    const days = Math.floor(seconds / 86400)
    seconds %= 86400
    const hours = Math.floor(seconds / 3600)
    seconds %= 3600
    const minutes = Math.floor(seconds / 60)
    if (days) return `${days}g ${hours}h`
    if (hours) return `${hours}h ${minutes}m`
    if (minutes) return `${minutes}m`
    return `${seconds}s`
  }

  function formatDate(value, includeSeconds = false) {
    if (!value) return 'mai'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '--'
    const options = {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    }
    if (includeSeconds) options.second = '2-digit'
    return new Intl.DateTimeFormat('it-IT', options).format(date)
  }

  function formatAge(seconds) {
    const numeric = finiteNumber(seconds)
    if (numeric === null) return 'Aggiornamento sconosciuto'
    if (numeric < 5) return 'Aggiornato ora'
    return `Aggiornato ${formatDuration(numeric)} fa`
  }

  function metricAge(metric) {
    const age = finiteNumber(metric?.age_seconds)
    if (age !== null) return age
    if (!metric?.timestamp) return null
    const timestamp = new Date(metric?.timestamp).getTime()
    return Number.isFinite(timestamp) ? Math.max(0, (Date.now() - timestamp) / 1000) : null
  }

  function metricValue(metrics, key) {
    const metric = metrics?.[key]
    if (!metric || !Object.hasOwn(metric, 'value')) return null
    return metric.value === null || metric.value === undefined ? null : metric.value
  }

  function metricMeta(metrics, keys, missing) {
    const available = keys.map((key) => metrics?.[key]).find((metric) => metricValue({ metric }, 'metric') !== null)
    if (available) return formatAge(metricAge(available))
    if (keys.some((key) => missing.has(key))) return 'Metrica non ricevuta'
    return 'Dato non disponibile'
  }

  function formatDockerPing(value) {
    if (value === null || value === undefined || value === '') return '--'
    if (value === true || value === 1 || value === '1') return 'Raggiungibile'
    const normalized = String(value).toLowerCase()
    if (['ok', 'up', 'healthy', 'running', 'true'].includes(normalized)) return 'Raggiungibile'
    return 'Non raggiungibile'
  }

  async function requestJson(url, key, timeout = 10000) {
    state.requests[key]?.abort()
    const controller = new AbortController()
    state.requests[key] = controller
    let timedOut = false
    const timer = window.setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeout)
    try {
      const response = await fetch(url, {
        cache: 'no-store',
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      })
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

  function setNotice(element, message = '', error = false) {
    if (!element) return
    setText(element, message)
    element.hidden = !message
    element.classList.toggle('error', error)
  }

  function renderHealth(status = {}, generatedAt = null) {
    const hasMetrics = status.available === true
    const lastUpdated = status.last_updated || generatedAt
    setText(elements.lastUpdated, formatDate(lastUpdated, true))
    if (!hasMetrics) {
      elements.healthBanner.dataset.state = 'unavailable'
      setText(elements.healthTitle, 'Nessuna telemetria VM')
      setText(elements.healthDetail, 'Il connector non ha ancora ricevuto metriche dalla macchina virtuale.')
    } else if (status.stale) {
      elements.healthBanner.dataset.state = 'stale'
      setText(elements.healthTitle, 'Telemetria non aggiornata')
      setText(elements.healthDetail, `L'ultimo campione risale a ${formatDate(lastUpdated, true)}. I valori potrebbero non descrivere lo stato attuale.`)
    } else if (status.partial) {
      elements.healthBanner.dataset.state = 'partial'
      setText(elements.healthTitle, 'Telemetria parziale')
      setText(elements.healthDetail, 'Il flusso è aggiornato; alcune metriche Linux o Docker non sono trasmesse dal connector.')
    } else {
      const age = metricAge({ timestamp: lastUpdated })
      const received = age === null ? formatDate(lastUpdated, true) : age < 5 ? 'ora' : `${formatDuration(age)} fa`
      elements.healthBanner.dataset.state = 'healthy'
      setText(elements.healthTitle, 'Telemetria operativa')
      setText(elements.healthDetail, `Flusso aggiornato; ultimo campione ricevuto ${received}.`)
    }
  }

  function renderSnapshot(data) {
    const metrics = data?.metrics || {}
    const missing = new Set(Array.isArray(data?.missing) ? data.missing : [])
    const metricCount = VM_KEYS.filter((key) => metricValue(metrics, key) !== null).length
    const noMetrics = data?.status?.available === false || metricCount === 0
    state.snapshot = data
    renderHealth({ ...(data?.status || {}), available: !noMetrics }, data?.generated_at)
    elements.emptyState.hidden = !noMetrics
    elements.telemetryContent.hidden = noMetrics
    if (noMetrics) return

    const cards = [
      ['vmCpu', formatPercent(metricValue(metrics, 'cpu.util_pct'))],
      ['vmMemory', formatPercent(metricValue(metrics, 'memory.util_pct'))],
      ['vmMemoryAvailable', formatBytes(metricValue(metrics, 'memory.available_bytes'))],
      ['vmLoad1', formatNumber(metricValue(metrics, 'load.1m'), 2)],
      ['vmLoad5', formatNumber(metricValue(metrics, 'load.5m'), 2)],
      ['vmLoad15', formatNumber(metricValue(metrics, 'load.15m'), 2)],
      ['vmDisk', formatPercent(metricValue(metrics, 'filesystem.root.util_pct'))],
      ['vmUptime', formatDuration(metricValue(metrics, 'uptime_seconds'))],
      ['vmNetworkRx', formatRate(metricValue(metrics, 'network.rx_bps'))],
      ['vmNetworkTx', formatRate(metricValue(metrics, 'network.tx_bps'))],
      ['dockerPing', formatDockerPing(metricValue(metrics, 'docker.ping'))],
      ['dockerTotal', formatNumber(metricValue(metrics, 'docker.containers.total'))],
      ['dockerRunning', formatNumber(metricValue(metrics, 'docker.containers.running'))],
      ['dockerStopped', formatNumber(metricValue(metrics, 'docker.containers.stopped'))],
      ['dockerPaused', formatNumber(metricValue(metrics, 'docker.containers.paused'))],
      ['dockerCpu', formatPercent(metricValue(metrics, 'docker.cpu_pct_sum'))],
      ['dockerMemory', formatBytes(metricValue(metrics, 'docker.memory_active_bytes'))],
    ]
    for (const [id, value] of cards) setTextById(id, value)

    const metadata = [
      ['vmCpuMeta', ['cpu.util_pct']],
      ['vmMemoryMeta', ['memory.util_pct', 'memory.available_bytes']],
      ['vmLoadMeta', ['load.1m', 'load.5m', 'load.15m']],
      ['vmDiskMeta', ['filesystem.root.util_pct']],
      ['vmUptimeMeta', ['uptime_seconds']],
      ['vmNetworkMeta', ['network.rx_bps', 'network.tx_bps']],
      ['dockerPingMeta', ['docker.ping']],
      ['dockerTotalMeta', ['docker.containers.total']],
      ['dockerRunningMeta', ['docker.containers.running']],
      ['dockerStoppedMeta', ['docker.containers.stopped']],
      ['dockerPausedMeta', ['docker.containers.paused']],
      ['dockerCpuMeta', ['docker.cpu_pct_sum']],
      ['dockerMemoryMeta', ['docker.memory_active_bytes']],
    ]
    for (const [id, keys] of metadata) setTextById(id, metricMeta(metrics, keys, missing))
  }

  function normalizeSeries(series) {
    if (!Array.isArray(series)) return []
    return series
      .map((point) => ({ timestamp: new Date(point?.timestamp).getTime(), value: finiteNumber(point?.value) }))
      .filter((point) => Number.isFinite(point.timestamp) && point.value !== null)
      .sort((left, right) => left.timestamp - right.timestamp)
  }

  function chartTimeLabel(timestamp, span, detailed = false) {
    const options = span > 36 * 60 * 60 * 1000
      ? { day: '2-digit', month: '2-digit' }
      : { hour: '2-digit', minute: '2-digit' }
    if (detailed && span > 36 * 60 * 60 * 1000) options.hour = '2-digit'
    return new Intl.DateTimeFormat('it-IT', options).format(new Date(timestamp))
  }

  function drawHistoryChart() {
    const canvas = elements.historyChart
    if (!canvas) return
    const context = canvas.getContext('2d')
    const rect = canvas.getBoundingClientRect()
    const width = Math.max(1, rect.width)
    const height = 300
    const ratio = Math.min(2, window.devicePixelRatio || 1)
    canvas.width = Math.floor(width * ratio)
    canvas.height = Math.floor(height * ratio)
    context.setTransform(ratio, 0, 0, ratio, 0, 0)
    context.clearRect(0, 0, width, height)

    const allPoints = [...state.history.cpu, ...state.history.memory]
    elements.chartEmpty.hidden = allPoints.length > 0
    if (!allPoints.length) {
      setText(elements.chartSummary, 'Nessun campione storico disponibile.')
      return
    }

    const requestedFrom = new Date(state.history.window?.from).getTime()
    const requestedTo = new Date(state.history.window?.to).getTime()
    const observedFrom = Math.min(...allPoints.map((point) => point.timestamp))
    const observedTo = Math.max(...allPoints.map((point) => point.timestamp))
    const from = Number.isFinite(requestedFrom) ? requestedFrom : observedFrom
    const to = Number.isFinite(requestedTo) ? requestedTo : Math.max(observedTo, from + 1)
    const span = Math.max(1, to - from)
    const pad = { left: 43, right: 16, top: 20, bottom: 34 }
    const plotWidth = Math.max(1, width - pad.left - pad.right)
    const plotHeight = height - pad.top - pad.bottom
    const styles = getComputedStyle(document.documentElement)
    const cpuColor = styles.getPropertyValue('--teal').trim() || '#4ce0c1'
    const memoryColor = styles.getPropertyValue('--coral').trim() || '#ff735c'

    context.lineWidth = 1
    context.font = '11px ui-monospace, monospace'
    context.textAlign = 'left'
    for (let index = 0; index <= 4; index += 1) {
      const y = pad.top + (plotHeight * index) / 4
      context.strokeStyle = 'rgba(196,220,199,.13)'
      context.beginPath()
      context.moveTo(pad.left, y)
      context.lineTo(width - pad.right, y)
      context.stroke()
      context.fillStyle = '#8ea29a'
      context.fillText(`${100 - index * 25}%`, 4, y + 4)
    }

    const drawLine = (points, color) => {
      if (!points.length) return
      context.beginPath()
      context.strokeStyle = color
      context.lineWidth = 2
      points.forEach((point, index) => {
        const x = pad.left + ((point.timestamp - from) / span) * plotWidth
        const y = pad.top + plotHeight - (Math.max(0, Math.min(100, point.value)) / 100) * plotHeight
        if (index === 0) context.moveTo(x, y)
        else context.lineTo(x, y)
      })
      context.stroke()
      if (points.length === 1) {
        const point = points[0]
        const x = pad.left + ((point.timestamp - from) / span) * plotWidth
        const y = pad.top + plotHeight - (Math.max(0, Math.min(100, point.value)) / 100) * plotHeight
        context.fillStyle = color
        context.beginPath()
        context.arc(x, y, 3, 0, Math.PI * 2)
        context.fill()
      }
    }
    drawLine(state.history.cpu, cpuColor)
    drawLine(state.history.memory, memoryColor)

    context.fillStyle = '#8ea29a'
    context.textAlign = 'left'
    context.fillText(chartTimeLabel(from, span), pad.left, height - 8)
    if (width >= 520) {
      context.textAlign = 'center'
      context.fillText(chartTimeLabel(from + span / 2, span, true), pad.left + plotWidth / 2, height - 8)
    }
    context.textAlign = 'right'
    context.fillText(chartTimeLabel(to, span), width - pad.right, height - 8)
    context.textAlign = 'left'

    const cpuValues = state.history.cpu.map((point) => point.value)
    const memoryValues = state.history.memory.map((point) => point.value)
    const cpuSummary = cpuValues.length ? `CPU da ${formatNumber(Math.min(...cpuValues), 1)}% a ${formatNumber(Math.max(...cpuValues), 1)}%` : 'CPU non disponibile'
    const memorySummary = memoryValues.length ? `memoria da ${formatNumber(Math.min(...memoryValues), 1)}% a ${formatNumber(Math.max(...memoryValues), 1)}%` : 'memoria non disponibile'
    setText(elements.chartSummary, `Storico: ${cpuSummary}; ${memorySummary}.`)
  }

  async function loadHistory() {
    const range = elements.historyRange.value
    try {
      const data = await requestJson(`/api/v1/vm/history?range=${encodeURIComponent(range)}`, 'history')
      if (range !== elements.historyRange.value) return
      state.history = {
        cpu: normalizeSeries(data?.series?.['cpu.util_pct']),
        memory: normalizeSeries(data?.series?.['memory.util_pct']),
        window: data?.window || null,
      }
      setNotice(elements.historyNotice)
      setText(elements.chartEmpty, 'Lo storico si popolerà con le trasmissioni del connector.')
      drawHistoryChart()
    } catch (error) {
      if (error.name === 'AbortError') return
      setNotice(elements.historyNotice, 'Storico temporaneamente non raggiungibile. Restano visibili gli ultimi campioni ricevuti.', true)
      if (!state.history.cpu.length && !state.history.memory.length) {
        setText(elements.chartEmpty, 'Storico temporaneamente non disponibile.')
        drawHistoryChart()
      }
    }
  }

  function appendTextElement(parent, tag, text, className = '') {
    const element = document.createElement(tag)
    if (className) element.className = className
    element.textContent = String(text)
    parent.append(element)
    return element
  }

  function renderDatasets(datasets) {
    elements.connectorDatasets.replaceChildren()
    const entries = Object.entries(datasets || {}).sort(([left], [right]) => left.localeCompare(right, 'it'))
    if (!entries.length) {
      const row = document.createElement('div')
      appendTextElement(row, 'dt', 'Dataset')
      appendTextElement(row, 'dd', 'Nessun dato')
      elements.connectorDatasets.append(row)
      return
    }
    for (const [name, dataset] of entries) {
      const row = document.createElement('div')
      appendTextElement(row, 'dt', name)
      const detail = dataset?.received === false
        ? 'Non ricevuto'
        : `${formatAge(dataset?.age_seconds)} · ${formatDate(dataset?.timestamp)}`
      appendTextElement(row, 'dd', detail)
      elements.connectorDatasets.append(row)
    }
  }

  function renderMissingMetrics(vm) {
    elements.connectorMissing.replaceChildren()
    const missing = Array.isArray(vm?.missing) ? vm.missing : []
    const received = Array.isArray(vm?.received) ? vm.received : []
    setTextById('connectorCoverage', `${received.length}/${received.length + missing.length} ricevute`)
    if (!missing.length) {
      appendTextElement(elements.connectorMissing, 'li', 'Copertura completa', 'complete')
      return
    }
    for (const key of missing) appendTextElement(elements.connectorMissing, 'li', key)
  }

  function describeCollection(value) {
    if (Array.isArray(value)) {
      return value.map((item) => {
        if (item === null || item === undefined) return ''
        if (typeof item !== 'object') return String(item)
        const name = item.key || item.name || item.item || 'elemento'
        return item.reason ? `${name}: ${item.reason}` : JSON.stringify(item)
      }).filter(Boolean).join(', ')
    }
    if (value && typeof value === 'object') return Object.keys(value).join(', ')
    return value === null || value === undefined || value === '' ? '—' : String(value)
  }

  function renderBatches(batches) {
    elements.connectorBatchesTable.replaceChildren()
    const recent = Array.isArray(batches) ? batches.slice(0, 20) : []
    if (!recent.length) {
      const row = document.createElement('tr')
      const cell = appendTextElement(row, 'td', 'Nessun batch disponibile.', 'empty-cell')
      cell.colSpan = 8
      elements.connectorBatchesTable.append(row)
      return
    }
    for (const batch of recent) {
      const row = document.createElement('tr')
      const values = [
        formatDate(batch?.received_at, true),
        describeCollection(batch?.source_hosts),
        formatNumber(batch?.record_count),
        formatNumber(batch?.accepted),
        formatNumber(batch?.ignored),
        formatNumber(batch?.rejected),
        describeCollection(batch?.datasets),
        describeCollection(batch?.ignored_items),
      ]
      for (const value of values) appendTextElement(row, 'td', value)
      elements.connectorBatchesTable.append(row)
    }
  }

  function renderConnector(data) {
    const summary = data?.summary || {}
    const values = [
      ['connectorLastReceived', formatDate(summary.last_received_at, true)],
      ['connectorBatches', formatNumber(summary.batches_24h)],
      ['connectorRecords', formatNumber(summary.records_24h)],
      ['connectorAccepted', formatNumber(summary.accepted_24h)],
      ['connectorIgnored', formatNumber(summary.ignored_24h)],
      ['connectorRejected', formatNumber(summary.rejected_24h)],
      ['connectorGenerated', `Generato ${formatDate(data?.generated_at, true)}`],
    ]
    for (const [id, value] of values) setTextById(id, value)
    renderDatasets(data?.datasets)
    renderMissingMetrics(data?.vm)
    renderBatches(data?.batches)
    setNotice(elements.connectorNotice)
  }

  async function loadConnector() {
    if (!elements.connectorSection) return
    try {
      renderConnector(await requestJson('/api/v1/connector/status', 'connector'))
    } catch (error) {
      if (error.name === 'AbortError') return
      setNotice(elements.connectorNotice, 'Diagnostica connector temporaneamente non raggiungibile.', true)
    }
  }

  async function loadSnapshot() {
    try {
      renderSnapshot(await requestJson('/api/v1/vm/snapshot', 'snapshot'))
    } catch (error) {
      if (error.name === 'AbortError') return
      elements.healthBanner.dataset.state = 'error'
      setText(elements.healthTitle, state.snapshot ? 'Aggiornamento interrotto' : 'Telemetria non raggiungibile')
      setText(elements.healthDetail, state.snapshot ? 'Continuo a mostrare gli ultimi valori ricevuti.' : 'Non è stato possibile contattare il servizio di telemetria VM.')
    }
  }

  async function pollSnapshot(generation) {
    if (document.hidden || generation !== state.pollGeneration) return
    await Promise.all([loadSnapshot(), loadConnector()])
    if (document.hidden || generation !== state.pollGeneration) return
    state.pollTimer = window.setTimeout(() => pollSnapshot(generation), POLL_INTERVAL)
  }

  function startPolling() {
    window.clearTimeout(state.pollTimer)
    const generation = ++state.pollGeneration
    pollSnapshot(generation)
  }

  function suspendRequests() {
    window.clearTimeout(state.pollTimer)
    state.pollGeneration += 1
    for (const controller of Object.values(state.requests)) controller.abort()
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
    elements.historyRange.addEventListener('change', loadHistory)
    window.addEventListener('resize', () => {
      window.cancelAnimationFrame(state.resizeFrame)
      state.resizeFrame = window.requestAnimationFrame(drawHistoryChart)
    })
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        suspendRequests()
        return
      }
      startPolling()
      loadHistory()
    })
    startPolling()
    loadHistory()
  }

  initialize()
})()
