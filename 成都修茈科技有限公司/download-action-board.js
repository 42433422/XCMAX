/**
 * 官网公开行动看板渲染（只读）。
 * 页面通过 body[data-board=breakpoints|goals] + data-accent=patch|update 选择看板。
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

  function fetchBoard(url, wrapped) {
    return fetch(url, { cache: 'no-store' })
      .then(function (r) {
        var ct = r.headers.get('content-type') || ''
        if (!r.ok || ct.indexOf('json') < 0) throw new Error('board ' + r.status)
        return r.json()
      })
      .then(function (payload) {
        if (!wrapped) return payload
        if (!payload || payload.ok !== true || !payload.data) throw new Error('live board unavailable')
        return payload.data
      })
  }

  function renderBoard(boardKey, accent) {
    var board = (window.__ACTION_BOARD__ && window.__ACTION_BOARD__[boardKey]) || null
    var meta = document.getElementById('board-meta')
    var sum = document.getElementById('board-sum')
    var list = document.getElementById('board-list')
    if (!meta || !sum || !list) return

    if (!board) {
      meta.textContent = '暂无公开数据'
      sum.innerHTML = ''
      list.innerHTML = '<div class="progress-empty">今日暂无条目（日更 digest 后自动刷新）。</div>'
      return
    }

    var s = board.summary || {}
    var day =
      (window.__ACTION_BOARD__ && window.__ACTION_BOARD__.day) ||
      (board.items && board.items[0] && board.items[0].day) ||
      '—'
    meta.textContent = day + ' · 共 ' + (s.total || 0) + ' 条 · 只读公开'

    if (accent === 'patch') {
      sum.innerHTML =
        '<div class="progress-sum-card is-p0"><strong>' +
        esc(s.p0 || 0) +
        '</strong><span>P0 紧急修复</span></div>' +
        '<div class="progress-sum-card is-todo"><strong>' +
        esc(s.p1_p2 || 0) +
        '</strong><span>P1/P2 待办</span></div>' +
        '<div class="progress-sum-card is-ok"><strong>' +
        esc((s.completion_rate || 0) + '%') +
        '</strong><span>完成率 · 已闭环 ' +
        esc(s.done || 0) +
        '</span></div>'
    } else {
      var lines = Object.keys(s.by_line || {}).length
      sum.innerHTML =
        '<div class="progress-sum-card is-blue"><strong>' +
        esc(s.total || 0) +
        '</strong><span>更新条目</span></div>' +
        '<div class="progress-sum-card is-todo"><strong>' +
        esc(lines) +
        '</strong><span>覆盖产线</span></div>' +
        '<div class="progress-sum-card is-ok"><strong>' +
        esc((s.completion_rate || 0) + '%') +
        '</strong><span>完成率 · 已落 ' +
        esc(s.done || 0) +
        '</span></div>'
    }

    var items = board.items || []
    if (!items.length) {
      list.innerHTML = '<div class="progress-empty">今日暂无条目（日更 digest 后自动刷新）。</div>'
      return
    }

    list.innerHTML = items
      .map(function (it) {
        var done = it.status === 'merged' || it.status === 'closed'
        var pri = done ? 'ok' : String(it.priority || 'P2').toLowerCase()
        var priLabel = done ? '已闭环' : esc(it.priority || 'P2')
        return (
          '<article class="progress-item' +
          (done ? ' is-done' : '') +
          '">' +
          '<span class="progress-pri ' +
          pri +
          '">' +
          priLabel +
          '</span>' +
          '<div><h2>' +
          esc(it.title) +
          '</h2>' +
          '<div class="progress-item-meta">' +
          '<span>' +
          esc(it.line_label || it.line || '—') +
          '</span>' +
          '<span>' +
          esc(it.owner || 'AI 员工') +
          '</span>' +
          '</div></div>' +
          '<span class="progress-status">' +
          esc(it.status_label || it.status || '') +
          '</span>' +
          '</article>'
        )
      })
      .join('')
  }

  function boot() {
    var boardKey = document.body.getAttribute('data-board') || 'breakpoints'
    var accent = document.body.getAttribute('data-accent') || 'patch'
    fetchBoard('/api/public/action-board', true)
      .catch(function () {
        return fetchBoard('/download-action-board.json', false)
      })
      .then(function (data) {
        window.__ACTION_BOARD__ = data || null
        renderBoard(boardKey, accent)
      })
      .catch(function () {
        window.__ACTION_BOARD__ = null
        renderBoard(boardKey, accent)
      })
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot)
  else boot()
})()
