;(function () {
  'use strict'

  const DATA_URL = '/api/public/visualization'
  const REFRESH_INTERVAL_MS = 60 * 1000
  const REQUEST_TIMEOUT_MS = 8 * 1000
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  let requestSequence = 0

  function readPath(source, path) {
    return path.split('.').reduce((value, key) => (value == null ? undefined : value[key]), source)
  }

  function formatDateTime(value) {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value || '—'
    return new Intl.DateTimeFormat('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(date)
  }

  function setStatus(state) {
    const status = document.getElementById('viz-data-status')
    const statusText = status && status.querySelector('span')
    const freshness = document.querySelector('[data-viz-freshness-label]')
    const messages = {
      loading: '正在连接',
      live: '实时数据',
      degraded: '部分数据暂不可用',
      offline: '实时连接失败',
    }
    document.documentElement.dataset.vizData = state
    if (status) status.dataset.state = state
    if (statusText) statusText.textContent = messages[state] || messages.offline
    if (freshness) {
      freshness.textContent = state === 'offline' ? '数据状态' : state === 'loading' ? '实时连接' : '生成时间'
    }
  }

  function paintText(data) {
    document.querySelectorAll('[data-viz-text]').forEach((element) => {
      const path = element.dataset.vizText
      const value = readPath(data, path)
      element.textContent = value == null || value === '' ? '—' : path === 'generated_at' ? formatDateTime(value) : String(value)
    })
  }

  function animateNumber(element, target) {
    const decimals = Number(element.dataset.decimals || 0)
    const render = (value) => {
      element.textContent = Number(value).toLocaleString('zh-CN', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })
    }
    const previous = Number(element.dataset.value)
    const from = Number.isFinite(previous) ? previous : target
    element.dataset.value = String(target)
    // 首次赋值直接落最终值，避免从 0 起动画闪成「查看 0 个版本节点」
    if (reduceMotion || from === target) {
      render(target)
      return
    }
    const start = performance.now()
    const duration = 900
    const delta = target - from
    const tick = (now) => {
      const progress = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - progress, 3)
      render(from + delta * eased)
      if (progress < 1) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }

  function paintNumbers(data) {
    document.querySelectorAll('[data-viz-number]').forEach((element) => {
      const raw = readPath(data, element.dataset.vizNumber)
      const value = raw == null ? Number.NaN : Number(raw)
      if (!Number.isFinite(value)) {
        element.textContent = '—'
        delete element.dataset.value
        return
      }
      animateNumber(element, value)
    })
  }

  function paintCompactNumbers(data) {
    document.querySelectorAll('[data-viz-compact-number]').forEach((element) => {
      const raw = readPath(data, element.dataset.vizCompactNumber)
      const value = raw == null ? Number.NaN : Number(raw)
      if (!Number.isFinite(value)) {
        element.textContent = '—'
      } else if (Math.abs(value) >= 100000000) {
        element.textContent = `${(value / 100000000).toFixed(2)} 亿`
      } else if (Math.abs(value) >= 10000) {
        element.textContent = `${(value / 10000).toFixed(1)} 万`
      } else {
        element.textContent = value.toLocaleString('zh-CN')
      }
    })
  }

  function paintWidths(data) {
    document.querySelectorAll('[data-viz-width]').forEach((element) => {
      const raw = readPath(data, element.dataset.vizWidth)
      const value = raw == null ? 0 : Number(raw)
      element.style.width = `${Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0}%`
    })

    const platforms = data.downloads && data.downloads.platforms
    const values = {
      windows: Number(platforms && platforms.windows) || 0,
      macos: Number(platforms && platforms.macos) || 0,
      android: Number(platforms && platforms.android) || 0,
    }
    const maximum = Math.max(values.windows, values.macos, values.android, 1)
    document.querySelectorAll('[data-viz-platform-bar]').forEach((element) => {
      const value = values[element.dataset.vizPlatformBar] || 0
      element.style.width = `${(value / maximum) * 100}%`
    })

    const total = Number(data.downloads && data.downloads.total) || 0
    const win = total > 0 ? (values.windows / total) * 100 : 0
    const mac = total > 0 ? (values.macos / total) * 100 : 0
    const ring = document.getElementById('viz-download-ring')
    if (ring) {
      ring.style.setProperty('--win', `${win}%`)
      ring.style.setProperty('--mac', `${win + mac}%`)
    }
  }

  function paintModelUsage(data) {
    const list = document.querySelector('[data-viz-model-list]')
    const count = document.querySelector('[data-viz-model-count]')
    const total = document.querySelector('[data-viz-model-total-calls]')
    if (!list) return

    const models = Array.isArray(data.ai && data.ai.chat_models)
      ? data.ai.chat_models
          .filter((item) => item && item.model)
          .slice()
          .sort((left, right) => (Number(right.calls) || 0) - (Number(left.calls) || 0))
      : []
    const totalCalls = models.reduce((sum, item) => sum + (Number(item.calls) || 0), 0)
    const maximumCalls = Math.max(...models.map((item) => Number(item.calls) || 0), 1)
    if (count) count.textContent = models.length ? models.length.toLocaleString('zh-CN') : '—'
    if (total) total.textContent = models.length ? totalCalls.toLocaleString('zh-CN') : '—'

    if (models.length === 0) {
      const empty = document.createElement('p')
      empty.className = 'viz-chart-empty'
      empty.textContent = '模型调用数据暂不可用'
      list.replaceChildren(empty)
      return
    }

    list.replaceChildren(
      ...models.map((item) => {
        const calls = Number(item.calls) || 0
        const tokens = Number(item.tokens) || 0
        const share = Number(item.share) || 0
        const row = document.createElement('div')
        row.className = 'viz-model-row'

        const identity = document.createElement('div')
        identity.className = 'viz-model-identity'
        const model = document.createElement('b')
        model.textContent = String(item.model)
        const provider = document.createElement('span')
        provider.textContent = String(item.provider || 'unknown')
        identity.append(model, provider)

        const usage = document.createElement('div')
        usage.className = 'viz-model-call'
        const usageValue = document.createElement('span')
        const usageNumber = document.createElement('b')
        usageNumber.textContent = calls.toLocaleString('zh-CN')
        usageValue.append(usageNumber, ' 次')
        const track = document.createElement('i')
        const fill = document.createElement('em')
        fill.style.width = `${(calls / maximumCalls) * 100}%`
        track.append(fill)
        usage.append(usageValue, track)

        const tokenValue = document.createElement('strong')
        tokenValue.className = 'viz-model-tokens'
        tokenValue.textContent = tokens.toLocaleString('zh-CN')

        const shareValue = document.createElement('strong')
        shareValue.className = 'viz-model-share'
        shareValue.textContent = share === 0 && tokens > 0 ? '<0.01%' : `${share.toFixed(2)}%`

        row.append(identity, usage, tokenValue, shareValue)
        return row
      }),
    )
  }

  function paintTrend(data) {
    const chart = document.getElementById('viz-trend-chart')
    const daily = data.downloads && data.downloads.daily
    if (!chart) return
    if (!Array.isArray(daily) || daily.length === 0) {
      chart.innerHTML = '<p class="viz-chart-empty">实时下载数据暂不可用</p>'
      return
    }
    const maximum = Math.max(...daily.map((item) => Number(item.count) || 0), 1)
    chart.replaceChildren(
      ...daily.map((item) => {
        const count = Number(item.count) || 0
        const day = document.createElement('div')
        day.className = `viz-day${count > 0 && count === maximum ? ' is-peak' : ''}`
        const bar = document.createElement('i')
        bar.style.setProperty('--h', `${(count / maximum) * 100}%`)
        const value = document.createElement('b')
        value.textContent = String(count)
        const date = document.createElement('span')
        date.textContent = item.date || '—'
        day.append(bar, value, date)
        return day
      }),
    )
  }

  function paintReleaseState(data) {
    const element = document.querySelector('[data-viz-release-status]')
    if (!element) return
    const value = data.product && data.product.release_status
    element.textContent = value || '—'
    element.classList.toggle('viz-ready', value === 'READY')
  }

  function formatCompactToken(value) {
    const number = Number(value) || 0
    if (Math.abs(number) >= 100000000) return `${(number / 100000000).toFixed(2)} 亿`
    if (Math.abs(number) >= 10000) return `${(number / 10000).toFixed(1)} 万`
    return number.toLocaleString('zh-CN')
  }

  function paintMadeSources(data) {
    const host = document.querySelector('[data-viz-made-sources]')
    if (!host) return
    const sources = Array.isArray(data.ai && data.ai.platform_made_sources)
      ? data.ai.platform_made_sources.filter((item) => item && item.available && Number(item.total_tokens) > 0)
      : []
    if (sources.length === 0) {
      host.replaceChildren()
      return
    }
    host.replaceChildren(
      ...sources.map((item) => {
        const row = document.createElement('div')
        row.className = 'viz-made-source-row'
        const label = document.createElement('span')
        label.textContent = String(item.label || item.key || '—')
        const value = document.createElement('b')
        value.textContent = formatCompactToken(item.total_tokens)
        if (item.estimated) {
          const tip = document.createElement('small')
          tip.textContent = '估'
          row.append(label, value, tip)
        } else {
          row.append(label, value)
        }
        return row
      }),
    )
  }

  function formatMonitorValue(value) {
    if (value == null || value === '') return '—'
    if (typeof value === 'number') return value.toLocaleString('zh-CN')
    return String(value)
  }

  function paintMonitor(data) {
    const grid = document.querySelector('[data-viz-monitor-grid]')
    const monitor = data.monitor || null
    if (!grid) return
    const dashboards = Array.isArray(monitor && monitor.dashboards) ? monitor.dashboards : []
    if (dashboards.length === 0) {
      const empty = document.createElement('p')
      empty.className = 'viz-chart-empty'
      empty.textContent = '监控聚合数据暂不可用'
      grid.replaceChildren(empty)
      return
    }
    const statusLabel = {
      live: 'LIVE',
      prom: 'PROM',
      logs: 'LOGS',
      k8s: 'K8S',
      offline: '离线',
      unavailable: '不可用',
    }
    grid.replaceChildren(
      ...dashboards.map((dash) => {
        const card = document.createElement('article')
        card.className = 'viz-mon-card reveal visible'
        card.dataset.monDash = String(dash.id || '')

        const head = document.createElement('div')
        head.className = 'viz-mon-card-head'
        const tag = document.createElement('span')
        tag.className = 'viz-mon-tag'
        tag.textContent = 'GRAF'
        const title = document.createElement('h3')
        title.textContent = String(dash.title || '—')
        const status = document.createElement('span')
        const mode = String(dash.status || 'offline')
        status.className = `viz-mon-status is-${mode}`
        status.textContent = statusLabel[mode] || mode
        head.append(tag, title, status)

        const desc = document.createElement('p')
        desc.className = 'viz-mon-desc'
        desc.textContent = String(dash.desc || '')

        const panels = document.createElement('div')
        panels.className = 'viz-mon-panels'
        const panelList = Array.isArray(dash.panels) ? dash.panels : []
        panels.append(
          ...panelList.map((panel) => {
            const cell = document.createElement('div')
            cell.className = 'viz-mon-panel'
            const label = document.createElement('span')
            label.textContent = String(panel.title || '—')
            const valueRow = document.createElement('div')
            const strong = document.createElement('strong')
            strong.className = `is-${panel.cls || 'c'}`
            strong.textContent = formatMonitorValue(panel.value)
            const unit = document.createElement('small')
            unit.textContent = String(panel.unit || '')
            valueRow.append(strong, unit)
            cell.append(label, valueRow)
            return cell
          }),
        )

        card.append(head, desc, panels)
        return card
      }),
    )
  }

  function clearLiveValues() {
    document.querySelectorAll('[data-viz-text], [data-viz-number], [data-viz-compact-number]').forEach((element) => {
      element.textContent = '—'
    })
    paintWidths({ downloads: null })
    paintModelUsage({ ai: null })
    paintTrend({ downloads: { daily: [] } })
    paintReleaseState({ product: null })
    paintMadeSources({ ai: null })
    paintMonitor({ monitor: null })
  }

  async function loadData() {
    const sequence = ++requestSequence
    const refresh = document.getElementById('viz-refresh')
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
    setStatus('loading')
    if (refresh) {
      refresh.disabled = true
      refresh.textContent = '读取中…'
    }
    try {
      const response = await fetch(`${DATA_URL}?t=${Date.now()}`, {
        cache: 'no-store',
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json()
      if (sequence !== requestSequence) return
      paintText(data)
      paintNumbers(data)
      paintCompactNumbers(data)
      paintWidths(data)
      paintModelUsage(data)
      paintTrend(data)
      paintReleaseState(data)
      paintMadeSources(data)
      paintMonitor(data)
      setStatus(data.data_status === 'live' ? 'live' : 'degraded')
    } catch (error) {
      if (sequence !== requestSequence) return
      clearLiveValues()
      setStatus('offline')
      console.warn('官网实时聚合数据读取失败。', error)
    } finally {
      window.clearTimeout(timeout)
      if (sequence === requestSequence && refresh) {
        refresh.disabled = false
        refresh.textContent = '立即刷新'
      }
    }
  }

  const refresh = document.getElementById('viz-refresh')
  if (refresh) refresh.addEventListener('click', loadData)
  window.setInterval(() => {
    if (!document.hidden) loadData()
  }, REFRESH_INTERVAL_MS)
  clearLiveValues()
  loadData()
})()
