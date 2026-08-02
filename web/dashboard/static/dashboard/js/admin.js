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
    commandTable: $('#commandPlayersTable'),
    commandStatus: $('#commandPlayersStatus'),
    commandRefresh: $('#refreshCommandPlayers'),
    commandNotice: $('#commandNotice'),
    announceForm: $('#announceForm'),
    announceMessage: $('#announceMessage'),
    announceStatus: $('#announceStatus'),
    unbanForm: $('#unbanForm'),
    unbanUserid: $('#unbanUserid'),
    unbanStatus: $('#unbanStatus'),
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

  function setCommandNotice(msg = '', error = false) {
    if (!elements.commandNotice) return
    setText(elements.commandNotice, msg)
    elements.commandNotice.hidden = !msg
    elements.commandNotice.classList.toggle('error', error)
  }

  function setStatus(el, msg = '', error = false) {
    if (!el) return
    setText(el, msg)
    el.classList.toggle('error', error)
  }

  function renderCommandPlayers(players) {
    if (!elements.commandTable) return
    elements.commandTable.replaceChildren()
    if (!players.length) {
      const row = document.createElement('tr')
      const cell = document.createElement('td')
      cell.colSpan = 5
      cell.className = 'empty-cell'
      cell.textContent = 'Nessun giocatore online.'
      row.appendChild(cell)
      elements.commandTable.appendChild(row)
      return
    }
    for (const p of players) {
      const row = document.createElement('tr')
      const name = document.createElement('td')
      const strong = document.createElement('strong')
      strong.textContent = p.name || '?'
      const userid = document.createElement('code')
      userid.textContent = p.userId
      name.append(strong, userid)
      const level = document.createElement('td')
      level.textContent = formatNumber(p.level)
      const ping = document.createElement('td')
      ping.textContent = `${formatNumber(p.ping, 1)} ms`
      const position = document.createElement('td')
      position.textContent = `X ${formatNumber(p.location_x)} / Y ${formatNumber(p.location_y)}`
      const actions = document.createElement('td')
      actions.className = 'actions-col'
      const kickBtn = document.createElement('button')
      kickBtn.type = 'button'
      kickBtn.className = 'action-btn small'
      kickBtn.textContent = 'Kick'
      kickBtn.dataset.userid = p.userId
      kickBtn.dataset.action = 'kick'
      const banBtn = document.createElement('button')
      banBtn.type = 'button'
      banBtn.className = 'action-btn small danger'
      banBtn.textContent = 'Ban'
      banBtn.dataset.userid = p.userId
      banBtn.dataset.action = 'ban'
      actions.append(kickBtn, banBtn)
      row.append(name, level, ping, position, actions)
      elements.commandTable.appendChild(row)
    }
  }

  async function loadCommandPlayers() {
    setStatus(elements.commandStatus, 'Caricamento...')
    setCommandNotice()
    try {
      const data = await requestJson('/api/v1/palworld/admin/players', 'command-players')
      renderCommandPlayers(data.players || [])
      setStatus(elements.commandStatus, `${formatNumber((data.players || []).length)} online`)
    } catch (error) {
      if (error.name === 'AbortError') return
      setStatus(elements.commandStatus, 'Non disponibile', true)
      setCommandNotice(error.message || 'Snapshot Palworld non disponibile.', true)
    }
  }

  async function runPlayerAction(action, userid, row) {
    const url = action === 'kick' ? '/api/v1/palworld/kick' : '/api/v1/palworld/ban'
    const playerName = row?.querySelector('strong')?.textContent || userid
    if (!window.confirm(`Confermi ${action === 'kick' ? 'il kick' : 'il ban'} di ${playerName} (${userid})?`)) return
    const rowButtons = row ? [...row.querySelectorAll('button')] : []
    rowButtons.forEach((button) => { button.disabled = true })
    const label = action === 'kick' ? 'Kick in corso...' : 'Ban in corso...'
    setStatus(elements.commandStatus, label)
    try {
      await requestJson(url, `cmd-${action}-${userid}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userid }),
      })
      setStatus(elements.commandStatus, action === 'kick' ? 'Giocatore espulso.' : 'Giocatore bannato.')
      if (row) row.remove()
      const remaining = elements.commandTable?.querySelectorAll('tr').length || 0
      if (!remaining) renderCommandPlayers([])
    } catch (error) {
      if (error.name === 'AbortError') return
      rowButtons.forEach((button) => { button.disabled = false })
      setStatus(elements.commandStatus, error.message || 'Azione non riuscita', true)
    }
  }

  async function handleAnnounceSubmit(event) {
    event.preventDefault()
    const message = (elements.announceMessage?.value || '').trim()
    if (!message) return
    const button = elements.announceForm?.querySelector('button[type="submit"]')
    if (button) button.disabled = true
    setStatus(elements.announceStatus, 'Invio in corso...')
    try {
      await requestJson('/api/v1/palworld/announce', 'announce', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      })
      setStatus(elements.announceStatus, 'Annuncio inviato.')
      elements.announceForm.reset()
    } catch (error) {
      if (error.name === 'AbortError') return
      setStatus(elements.announceStatus, error.message || 'Annuncio non riuscito', true)
    } finally {
      if (button) button.disabled = false
    }
  }

  async function handleUnbanSubmit(event) {
    event.preventDefault()
    const userid = (elements.unbanUserid?.value || '').trim()
    if (!userid) return
    const button = elements.unbanForm?.querySelector('button[type="submit"]')
    if (button) button.disabled = true
    setStatus(elements.unbanStatus, 'Revoca in corso...')
    try {
      await requestJson('/api/v1/palworld/unban', 'unban', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userid }),
      })
      setStatus(elements.unbanStatus, `Ban revocato per ${userid}.`)
      elements.unbanForm.reset()
    } catch (error) {
      if (error.name === 'AbortError') return
      setStatus(elements.unbanStatus, error.message || 'Revoca non riuscita', true)
    } finally {
      if (button) button.disabled = false
    }
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
    elements.commandRefresh?.addEventListener('click', loadCommandPlayers)
    elements.announceForm?.addEventListener('submit', handleAnnounceSubmit)
    elements.unbanForm?.addEventListener('submit', handleUnbanSubmit)
    elements.commandTable?.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-action][data-userid]')
      if (!button || !elements.commandTable.contains(button)) return
      runPlayerAction(button.dataset.action, button.dataset.userid, button.closest('tr'))
    })
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) return
      startPolling()
      loadInfo()
      loadAlerts().then(scheduleAlertPoll)
    })
    startPolling()
    loadInfo()
    loadCommandPlayers()
    scheduleInfoPoll()
    loadAlerts().then(scheduleAlertPoll)
  }

  initialize()
})()
