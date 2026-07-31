(() => {
  'use strict'

  const THEMES = new Set(['observatory', 'tron', 'ares', 'clu', 'athena', 'aphrodite', 'poseidon'])
  const state = { requests: {}, pollTimer: null, pollGeneration: 0, pollFailures: 0, alertTimer: null, infoTimer: null }

  const $ = (selector) => document.querySelector(selector)
  const elements = {
    table: $('#adminPlayersTable'),
    status: $('#playerListStatus'),
    refresh: $('#refreshPlayers'),
    notice: $('#adminNotice'),
    refreshInfo: $('#refreshInfo'),
    info: $('#adminServerInfo'),
    alerts: $('#saveAlerts'),
    alertsUpdated: $('#saveAlertsUpdated'),
  }

  function setText(el, v) { if (el && el.textContent !== String(v)) el.textContent = String(v) }

  function setNotice(msg = '', error = false) {
    if (!elements.notice) return
    setText(elements.notice, msg)
    elements.notice.hidden = !msg
    elements.notice.classList.toggle('error', error)
  }

  async function requestJson(url, key, options = {}, timeout = 10000) {
    state.requests[key]?.abort()
    const controller = new AbortController()
    state.requests[key] = controller
    let timedOut = false
    const timer = window.setTimeout(() => { timedOut = true; controller.abort() }, timeout)
    try {
      const response = await fetch(url, { ...options, cache: 'no-store', credentials: 'same-origin', headers: { ...(options.headers || {}), 'X-CSRFToken': getCsrfToken() }, signal: controller.signal })
      const data = await response.json()
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`)
      return data
    } catch (error) {
      if (timedOut) { const e = new Error('timeout'); e.name = 'TimeoutError'; throw e }
      throw error
    } finally {
      window.clearTimeout(timer)
      if (state.requests[key] === controller) delete state.requests[key]
    }
  }

  function getCsrfToken() {
    const cookie = document.cookie.match(/csrftoken=([^;]+)/)
    return cookie ? cookie[1] : ''
  }

  function formatNumber(v, d = 0) { const n = Number(v); return Number.isFinite(n) ? n.toLocaleString('it-IT', { maximumFractionDigits: d }) : '--' }

  function formatDate(v) {
    const date = new Date(v)
    return !v || Number.isNaN(date.getTime())
      ? 'mai'
      : new Intl.DateTimeFormat('it-IT', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(date)
  }

  function renderAlerts(data) {
    if (!elements.alerts) return
    elements.alerts.replaceChildren()
    const alerts = Array.isArray(data.alerts) ? data.alerts : []
    if (!alerts.length) {
      const card = document.createElement('article')
      card.className = 'admin-alert ok'
      const title = document.createElement('strong')
      const detail = document.createElement('span')
      title.textContent = 'Nessuna anomalia rilevata'
      detail.textContent = 'Gilde, basi e sincronizzazione risultano regolari.'
      card.append(title, detail)
      elements.alerts.appendChild(card)
    } else {
      for (const alert of alerts) {
        const card = document.createElement('article')
        card.className = `admin-alert ${alert.level === 'danger' ? 'danger' : 'warning'}`
        const title = document.createElement('strong')
        const detail = document.createElement('span')
        title.textContent = alert.title || 'Avviso'
        detail.textContent = alert.detail || ''
        card.append(title, detail)
        elements.alerts.appendChild(card)
      }
    }
    setText(elements.alertsUpdated, `Snapshot aggiornato: ${formatDate(data.updated_at)}`)
  }

  async function loadAlerts() {
    if (!elements.alerts) return
    try {
      renderAlerts(await requestJson('/api/v1/guild/data', 'save-alerts'))
    } catch (error) {
      if (error.name === 'AbortError') return
      elements.alerts.replaceChildren()
      const message = document.createElement('p')
      message.className = 'empty-copy'
      message.textContent = 'Avvisi del salvataggio temporaneamente non disponibili.'
      elements.alerts.appendChild(message)
    }
  }

  function scheduleAlertPoll() {
    window.clearTimeout(state.alertTimer)
    state.alertTimer = window.setTimeout(async () => {
      if (!document.hidden) await loadAlerts()
      scheduleAlertPoll()
    }, 120000)
  }

  function renderPlayers(players) {
    elements.table.replaceChildren()
    if (!players.length) {
      const row = document.createElement('tr')
      const cell = document.createElement('td')
      cell.colSpan = 4
      cell.className = 'empty-cell'
      cell.textContent = 'Nessun giocatore online.'
      row.appendChild(cell)
      elements.table.appendChild(row)
      return
    }
    for (const p of players) {
      const row = document.createElement('tr')
      const name = document.createElement('td')
      const strong = document.createElement('strong')
      strong.textContent = p.name || p.playerName || '?'
      name.appendChild(strong)
      const level = document.createElement('td')
      level.textContent = formatNumber(p.level)
      const ping = document.createElement('td')
      ping.textContent = `${formatNumber(p.ping, 1)} ms`
      const position = document.createElement('td')
      position.textContent = `X ${formatNumber(p.location_x)} / Y ${formatNumber(p.location_y)}`
      row.append(name, level, ping, position)
      elements.table.appendChild(row)
    }
  }

  async function loadPlayers() {
    setText(elements.status, 'Caricamento...')
    try {
      const data = await requestJson('/api/v1/palworld/players', 'players')
      renderPlayers(data.players || [])
      const prefix = data.stale ? 'ultimo snapshot' : 'online'
      setText(elements.status, `${formatNumber((data.players || []).length)} ${prefix} · ${formatDate(data.generated_at)}`)
      setNotice(!data.available
        ? 'Nessuno snapshot giocatori ancora disponibile.'
        : (data.stale ? 'Elenco in ritardo: le righe non rappresentano necessariamente lo stato online corrente.' : ''))
      state.pollFailures = data.stale ? Math.min(state.pollFailures + 1, 4) : 0
      return true
    } catch (error) {
      if (error.name === 'AbortError') return false
      setText(elements.status, 'Non disponibile')
      setNotice('Snapshot Palworld temporaneamente non disponibile.', true)
      state.pollFailures = Math.min(state.pollFailures + 1, 4)
      return false
    }
  }

  async function loadInfo() {
    try {
      const info = await requestJson('/api/v1/palworld/info', 'info')
      elements.info.replaceChildren()
      const entries = [
        ['Server', info.servername],
        ['Versione', info.version],
        ['Descrizione', info.description],
        ['Snapshot Palworld', formatDate(info.generated_at)],
        ['Freschezza', info.stale ? 'In ritardo' : 'Regolare'],
      ]
      for (const [label, value] of entries) {
        if (!value) continue
        const div = document.createElement('div')
        const dt = document.createElement('dt')
        dt.textContent = label
        const dd = document.createElement('dd')
        dd.textContent = value
        div.append(dt, dd)
        elements.info.appendChild(div)
      }
    } catch (error) {
      if (error.name !== 'AbortError') setText(elements.info, 'Non disponibile')
    }
  }

  function startPolling() {
    window.clearTimeout(state.pollTimer)
    const gen = ++state.pollGeneration
    const tick = async () => {
      if (document.hidden || gen !== state.pollGeneration) return
      await loadPlayers()
      if (gen !== state.pollGeneration) return
      const delay = Math.min(300000, 20000 * (2 ** state.pollFailures))
      state.pollTimer = window.setTimeout(tick, delay)
    }
    tick()
  }

  function scheduleInfoPoll() {
    window.clearTimeout(state.infoTimer)
    state.infoTimer = window.setTimeout(async () => {
      if (!document.hidden) await loadInfo()
      scheduleInfoPoll()
    }, 60000)
  }

  function initializeTheme() {
    try {
      const stored = window.localStorage.getItem('observatory.theme') || 'observatory'
      document.documentElement.dataset.theme = THEMES.has(stored) ? stored : 'observatory'
    } catch (_) { document.documentElement.dataset.theme = 'observatory' }
  }

  function initialize() {
    initializeTheme()
    elements.refresh?.addEventListener('click', loadPlayers)
    elements.refreshInfo?.addEventListener('click', loadInfo)
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) return
      startPolling()
      loadInfo()
      loadAlerts().then(scheduleAlertPoll)
    })
    startPolling()
    loadInfo()
    scheduleInfoPoll()
    loadAlerts().then(scheduleAlertPoll)
  }

  initialize()
})()
