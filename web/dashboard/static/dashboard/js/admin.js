(() => {
  'use strict'

  const THEMES = new Set(['observatory', 'tron', 'ares', 'clu', 'athena', 'aphrodite', 'poseidon'])
  const state = { requests: {}, pollTimer: null, pollGeneration: 0 }

  const $ = (selector) => document.querySelector(selector)
  const elements = {
    table: $('#adminPlayersTable'),
    status: $('#playerListStatus'),
    refresh: $('#refreshPlayers'),
    notice: $('#adminNotice'),
    form: $('#announceForm'),
    message: $('#announceMessage'),
    result: $('#announceResult'),
    refreshInfo: $('#refreshInfo'),
    info: $('#adminServerInfo'),
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
      const uid = document.createElement('td')
      const code = document.createElement('code')
      code.textContent = p.userId || p.playerId || '?'
      uid.appendChild(code)
      const actions = document.createElement('td')
      actions.className = 'admin-actions'
      const kickBtn = document.createElement('button')
      kickBtn.type = 'button'
      kickBtn.textContent = 'Kick'
      kickBtn.className = 'action-btn warn'
      kickBtn.addEventListener('click', () => doAction('kick', p.userId || p.playerId, kickBtn))
      const banBtn = document.createElement('button')
      banBtn.type = 'button'
      banBtn.textContent = 'Ban'
      banBtn.className = 'action-btn danger'
      banBtn.addEventListener('click', () => doAction('ban', p.userId || p.playerId, banBtn))
      actions.append(kickBtn, banBtn)
      row.append(name, level, uid, actions)
      elements.table.appendChild(row)
    }
  }

  async function loadPlayers() {
    setText(elements.status, 'Caricamento...')
    try {
      const data = await requestJson('/api/v1/palworld/players', 'players')
      renderPlayers(data.players || [])
      setText(elements.status, `${formatNumber((data.players || []).length)} giocatori online`)
      setNotice()
    } catch (error) {
      if (error.name === 'AbortError') return
      setText(elements.status, 'Non disponibile')
      setNotice('Impossibile contattare il server Palworld.', true)
    }
  }

  async function doAction(action, uid, btn) {
    if (!uid) return
    if (!confirm(`Confermi di fare ${action} a ${uid}?`)) return
    const original = btn.textContent
    btn.disabled = true
    btn.textContent = '...'
    try {
      await requestJson(`/api/v1/palworld/${action}`, action, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userid: uid }),
      })
      btn.textContent = 'Fatto'
      setTimeout(() => { btn.textContent = original; btn.disabled = false }, 1500)
      if (action === 'kick') setTimeout(loadPlayers, 1000)
    } catch (error) {
      btn.textContent = 'Errore'
      setTimeout(() => { btn.textContent = original; btn.disabled = false }, 2000)
      setNotice(`Operazione ${action} fallita: ${error.message}`, true)
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
        ['World GUID', info.worldguid],
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
      state.pollTimer = window.setTimeout(tick, 15000)
    }
    tick()
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
    elements.form?.addEventListener('submit', async (e) => {
      e.preventDefault()
      const msg = elements.message.value.trim()
      if (!msg) return
      elements.result.textContent = 'Invio...'
      try {
        await requestJson('/api/v1/palworld/announce', 'announce', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg }),
        })
        elements.result.textContent = 'Messaggio inviato!'
        elements.message.value = ''
        setTimeout(() => { elements.result.textContent = '' }, 3000)
      } catch (error) {
        elements.result.textContent = `Errore: ${error.message}`
      }
    })
    document.addEventListener('visibilitychange', () => { if (!document.hidden) startPolling() })
    startPolling()
    loadInfo()
  }

  initialize()
})()
