(() => {
  'use strict'

  const THEMES = new Set(['observatory', 'tron', 'ares', 'clu', 'athena', 'aphrodite', 'poseidon'])

  const state = {
    range: '30d',
    data: null,
    requests: {},
    pollTimer: null,
    pollGeneration: 0,
  }

  const $ = (selector) => document.querySelector(selector)
  const elements = {
    tabs: $('#leaderboardTabs'),
    playtimeBody: $('#leaderboardPlaytimeBody'),
    levelBody: $('#leaderboardLevelBody'),
    notice: $('#leaderboardNotice'),
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

  function formatDate(value) {
    if (!value) return 'mai'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '--'
    return new Intl.DateTimeFormat('it-IT', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(date)
  }

  function setNotice(message = '', error = false) {
    if (!elements.notice) return
    setText(elements.notice, message)
    elements.notice.hidden = !message
    elements.notice.classList.toggle('error', error)
  }

  function renderRow(cells, rank) {
    const row = document.createElement('tr')
    const rankCell = document.createElement('td')
    rankCell.textContent = String(rank)
    row.appendChild(rankCell)
    for (const cell of cells) row.appendChild(cell)
    return row
  }

  function nameCell(entry) {
    const cell = document.createElement('td')
    const name = document.createElement('strong')
    name.textContent = entry.name
    const account = document.createElement('small')
    account.textContent = entry.account_name || 'account non disponibile'
    cell.append(name, account)
    return cell
  }

  function statusCell(online) {
    const cell = document.createElement('td')
    const badge = document.createElement('span')
    badge.className = online ? 'status-badge online' : 'status-badge'
    badge.textContent = online ? 'Online' : 'Offline'
    cell.appendChild(badge)
    return cell
  }

  function renderPlaytime(entries, range) {
    elements.playtimeBody.replaceChildren()
    if (!entries.length) {
      const row = document.createElement('tr')
      const cell = document.createElement('td')
      cell.colSpan = 6
      cell.className = 'empty-cell'
      cell.textContent = 'Nessun giocatore registrato.'
      row.appendChild(cell)
      elements.playtimeBody.appendChild(row)
      return
    }
    const minutesKey = { '30d': 'minutes_30d', '365d': 'minutes_365d', all: 'minutes_all' }[range]
    entries.forEach((entry, index) => {
      const level = document.createElement('td')
      level.textContent = formatNumber(entry.level)
      const time = document.createElement('td')
      time.textContent = formatDuration(entry[minutesKey])
      const last = document.createElement('td')
      last.textContent = formatDate(entry.last_seen)
      const row = renderRow([nameCell(entry), level, time, last, statusCell(entry.online)], index + 1)
      elements.playtimeBody.appendChild(row)
    })
  }

  function renderLevel(entries) {
    elements.levelBody.replaceChildren()
    if (!entries.length) {
      const row = document.createElement('tr')
      const cell = document.createElement('td')
      cell.colSpan = 5
      cell.className = 'empty-cell'
      cell.textContent = 'Nessun giocatore registrato.'
      row.appendChild(cell)
      elements.levelBody.appendChild(row)
      return
    }
    entries.forEach((entry, index) => {
      const level = document.createElement('td')
      const strong = document.createElement('strong')
      strong.textContent = formatNumber(entry.level)
      level.appendChild(strong)
      const time = document.createElement('td')
      time.textContent = formatDuration(entry.minutes_365d)
      const last = document.createElement('td')
      last.textContent = formatDate(entry.last_seen)
      const row = renderRow([nameCell(entry), level, time, last], index + 1)
      elements.levelBody.appendChild(row)
    })
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

  async function load() {
    try {
      const data = await requestJson('/api/v1/leaderboard', 'leaderboard')
      state.data = data
      renderPlaytime(data.by_playtime[state.range] || [], state.range)
      renderLevel(data.by_level || [])
      setNotice()
    } catch (error) {
      if (error.name === 'AbortError') return
      setNotice('Classifica temporaneamente non disponibile.', true)
    }
  }

  function startPolling() {
    window.clearTimeout(state.pollTimer)
    const generation = ++state.pollGeneration
    const tick = async () => {
      if (document.hidden || generation !== state.pollGeneration) return
      await load()
      if (generation !== state.pollGeneration) return
      state.pollTimer = window.setTimeout(tick, 60000)
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
    if (elements.tabs) {
      for (const button of elements.tabs.querySelectorAll('button')) {
        button.addEventListener('click', () => {
          const range = button.dataset.range
          if (!range || range === state.range) return
          state.range = range
          for (const other of elements.tabs.querySelectorAll('button')) {
            other.setAttribute('aria-selected', String(other === button))
          }
          if (state.data) renderPlaytime(state.data.by_playtime[range] || [], range)
        })
      }
    }
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) return
      startPolling()
    })
    startPolling()
  }

  initialize()
})()
