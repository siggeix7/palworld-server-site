(() => {
  'use strict'

  const THEMES = new Set(['observatory', 'tron', 'ares', 'clu', 'athena', 'aphrodite', 'poseidon'])
  const state = { requests: {}, pollTimer: null, pollGeneration: 0 }

  const $ = (selector) => document.querySelector(selector)
  const elements = {
    content: $('#guildsContent'),
    empty: $('#guildsEmpty'),
    notice: $('#guildNotice'),
    updated: $('#guildUpdated'),
  }

  function setText(el, v) { if (el && el.textContent !== String(v)) el.textContent = String(v) }

  function setNotice(msg = '', error = false) {
    if (!elements.notice) return
    setText(elements.notice, msg)
    elements.notice.hidden = !msg
    elements.notice.classList.toggle('error', error)
  }

  function formatNumber(v, d = 0) { const n = Number(v); return Number.isFinite(n) ? n.toLocaleString('it-IT', { maximumFractionDigits: d }) : '--' }

  function formatDate(v) {
    if (!v) return 'mai'
    const d = new Date(v)
    return Number.isNaN(d.getTime()) ? '--' : new Intl.DateTimeFormat('it-IT', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(d)
  }

  async function requestJson(url, key, timeout = 10000) {
    state.requests[key]?.abort()
    const controller = new AbortController()
    state.requests[key] = controller
    let timedOut = false
    const timer = window.setTimeout(() => { timedOut = true; controller.abort() }, timeout)
    try {
      const r = await fetch(url, { cache: 'no-store', credentials: 'same-origin', signal: controller.signal })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return await r.json()
    } catch (e) {
      if (timedOut) { const t = new Error('timeout'); t.name = 'TimeoutError'; throw t }
      throw e
    } finally {
      window.clearTimeout(timer)
      if (state.requests[key] === controller) delete state.requests[key]
    }
  }

  function renderGuilds(data) {
    elements.content.replaceChildren()
    const guilds = data.guilds || []
    if (!guilds.length) {
      const p = document.createElement('p')
      p.className = 'empty-copy'
      p.textContent = 'Nessuna gilda disponibile.'
      elements.content.appendChild(p)
      return
    }
    for (const guild of guilds) {
      const card = document.createElement('article')
      card.className = 'guild-card'
      const header = document.createElement('header')
      const name = document.createElement('h3')
      name.textContent = guild.name || guild.guild_name || 'Gilda senza nome'
      const meta = document.createElement('span')
      meta.className = 'guild-meta'
      meta.textContent = `${formatNumber((guild.players || []).length)} membri · ${formatNumber((guild.base_ids || []).length)} basi`
      header.append(name, meta)
      card.appendChild(header)

      const players = guild.players || []
      if (players.length) {
        const dl = document.createElement('dl')
        dl.className = 'guild-players'
        for (const p of players) {
          const div = document.createElement('div')
          const dt = document.createElement('dt')
          dt.textContent = p.player_name || p.name || '?'
          const dd = document.createElement('dd')
          const isAdmin = guild.admin_player_uid === p.player_uid
          dd.textContent = isAdmin ? 'Capo gilda' : 'Membro'
          div.append(dt, dd)
          dl.appendChild(div)
        }
        card.appendChild(dl)
      }

      const bases = guild.base_ids || []
      if (bases.length) {
        const section = document.createElement('div')
        section.className = 'guild-bases'
        const label = document.createElement('p')
        label.className = 'archive-note'
        label.textContent = `Basi (${bases.length}):`
        section.appendChild(label)
        const list = document.createElement('ul')
        for (const b of bases) {
          const li = document.createElement('li')
          li.textContent = b
          list.appendChild(li)
        }
        section.appendChild(list)
        card.appendChild(section)
      }

      elements.content.appendChild(card)
    }
  }

  async function load() {
    try {
      const data = await requestJson('/api/v1/guild/data', 'guilds')
      renderGuilds(data)
      setText(elements.updated, `Aggiornato: ${formatDate(data.updated_at)}`)
      setNotice()
    } catch (error) {
      if (error.name === 'AbortError') return
      setNotice('Dati gilde temporaneamente non disponibili.', true)
    }
  }

  function startPolling() {
    window.clearTimeout(state.pollTimer)
    const gen = ++state.pollGeneration
    const tick = async () => {
      if (document.hidden || gen !== state.pollGeneration) return
      await load()
      if (gen !== state.pollGeneration) return
      state.pollTimer = window.setTimeout(tick, 120000)
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
    document.addEventListener('visibilitychange', () => { if (!document.hidden) startPolling() })
    startPolling()
  }

  initialize()
})()
