/**
 * 世界意志页：渲染公开行动看板真实轨迹 / 断点 / 目标。
 * 数据：/download-action-board.json（cache: no-store）
 */
;(function () {
  'use strict'

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
  }

  function fmtGen(iso) {
    if (!iso) return '—'
    try {
      var d = new Date(iso)
      if (isNaN(d.getTime())) return String(iso)
      return d.toLocaleString('zh-CN', { hour12: false })
    } catch (e) {
      return String(iso)
    }
  }

  function badgeClass(status) {
    if (status === 'merged' || status === 'closed') return 'is-done'
    if (status === 'open' || status === 'dispatched' || status === 'in_progress') return 'is-open'
    return ''
  }

  function emptyHtml(msg) {
    return '<div class="ww-empty">' + esc(msg) + '</div>'
  }

  function renderList(el, items, emptyMsg) {
    if (!el) return
    if (!items || !items.length) {
      el.innerHTML = emptyHtml(emptyMsg)
      return
    }
    el.innerHTML = items
      .slice(0, 12)
      .map(function (it) {
        return (
          '<article class="ww-row">' +
          '<h3>' +
          esc(it.title || '') +
          '</h3>' +
          '<div class="ww-item-meta">' +
          '<span class="ww-badge ' +
          badgeClass(it.status) +
          '">' +
          esc(it.status_label || it.status || '') +
          '</span>' +
          '<span>' +
          esc(it.line_label || it.line || '—') +
          '</span>' +
          '<span>' +
          esc(it.owner || 'AI 员工') +
          '</span>' +
          (it.ts ? '<span>' + esc(it.ts) + '</span>' : '') +
          (it.priority ? '<span>' + esc(it.priority) + '</span>' : '') +
          '</div></article>'
        )
      })
      .join('')
  }

  function renderTrajectory(el, items) {
    if (!el) return
    if (!items || !items.length) {
      el.innerHTML = emptyHtml('暂无公开轨迹（digest 写入后自动出现真实条目）。')
      return
    }
    el.innerHTML = items
      .map(function (it) {
        var href = it.href || (it.kind === 'patch' ? '/download/breakpoints' : '/download/goals')
        var title = it.title || it.text || ''
        return (
          '<a class="ww-item" href="' +
          esc(href) +
          '">' +
          '<time datetime="' +
          esc(it.updated_at || it.day || '') +
          '">' +
          esc(it.ts || '—') +
          '</time>' +
          '<div><h3>' +
          esc(title) +
          '</h3>' +
          '<div class="ww-item-meta">' +
          '<span class="ww-badge ' +
          badgeClass(it.status) +
          '">' +
          esc(it.status_label || it.status || '') +
          '</span>' +
          '<span>' +
          esc(it.owner || '') +
          '</span>' +
          '<span>' +
          esc(it.line || '') +
          '</span>' +
          (it.day ? '<span>' + esc(it.day) + '</span>' : '') +
          '</div></div></a>'
        )
      })
      .join('')
  }

  function render(data) {
    var day = (data && data.day) || '—'
    var gen = fmtGen(data && data.generated_at)
    var bp = (data && data.breakpoints) || {}
    var goals = (data && data.goals) || {}
    var traj = (data && data.trajectory) || []
    var bpItems = bp.items || []
    var goalItems = goals.items || []
    var bpSum = bp.summary || {}
    var gSum = goals.summary || {}

    var meta = document.getElementById('ww-meta')
    if (meta) {
      meta.textContent =
        '业务日 ' + day + ' · 快照刷新 ' + gen + ' · 只读公开 · schema ' + ((data && data.schema) || '—')
    }

    var sum = document.getElementById('ww-sum')
    if (sum) {
      sum.innerHTML =
        '<div class="ww-sum-card is-live"><strong>' +
        esc(traj.length) +
        '</strong><span>真实轨迹条数</span></div>' +
        '<div class="ww-sum-card is-p0"><strong>' +
        esc(bpSum.p0 || 0) +
        '</strong><span>P0 断点</span></div>' +
        '<div class="ww-sum-card is-todo"><strong>' +
        esc(bpSum.total || bpItems.length || 0) +
        '</strong><span>断点合计</span></div>' +
        '<div class="ww-sum-card is-blue"><strong>' +
        esc(gSum.total || goalItems.length || 0) +
        '</strong><span>工作目标</span></div>'
    }

    var count = document.getElementById('ww-traj-count')
    if (count) count.textContent = traj.length + ' 条'

    // 轨迹条目补 status_label / title，便于列表展示
    var enriched = traj.map(function (it) {
      var row = Object.assign({}, it)
      if (!row.title && row.text) {
        var parts = String(row.text).split('：')
        row.title = parts.length > 1 ? parts.slice(1).join('：') : row.text
        if (!row.status_label && parts[0]) {
          row.status_label = parts[0].split(' · ')[0]
        }
      }
      return row
    })

    renderTrajectory(document.getElementById('ww-traj'), enriched)
    renderList(document.getElementById('ww-breakpoints'), bpItems, '当日暂无公开断点。')
    renderList(document.getElementById('ww-goals'), goalItems, '当日暂无公开工作目标。')
  }

  function bootEmpty(msg) {
    var meta = document.getElementById('ww-meta')
    if (meta) meta.textContent = msg
    render({
      day: '—',
      generated_at: '',
      schema: 'unavailable',
      trajectory: [],
      breakpoints: { items: [], summary: {} },
      goals: { items: [], summary: {} },
    })
  }

  fetch('/download-action-board.json', { cache: 'no-store' })
    .then(function (res) {
      if (!res.ok) throw new Error('board ' + res.status)
      return res.json()
    })
    .then(render)
    .catch(function () {
      bootEmpty('公开看板暂不可用（未造假数据）。')
    })
})()
