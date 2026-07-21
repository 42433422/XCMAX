/**
 * 官网公开行动看板渲染（只读）。
 * 页面通过 body[data-board=breakpoints|goals] + data-accent=patch|update 选择看板。
 * 使用 DOM API（不用 innerHTML），避免静态扫描误报 XSS。
 */
;(function () {
  'use strict'

  function el(tag, className, text) {
    var node = document.createElement(tag)
    if (className) node.className = className
    if (text != null && text !== '') node.textContent = String(text)
    return node
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild)
  }

  function sumCard(className, strongText, spanText) {
    var card = el('div', 'progress-sum-card ' + className)
    card.appendChild(el('strong', '', strongText))
    card.appendChild(el('span', '', spanText))
    return card
  }

  function renderBoard(boardKey, accent) {
    var board = (window.__ACTION_BOARD__ && window.__ACTION_BOARD__[boardKey]) || null
    var meta = document.getElementById('board-meta')
    var sum = document.getElementById('board-sum')
    var list = document.getElementById('board-list')
    if (!meta || !sum || !list) return

    clear(sum)
    clear(list)

    if (!board) {
      meta.textContent = '暂无公开数据'
      list.appendChild(el('div', 'progress-empty', '今日暂无条目（日更 digest 后自动刷新）。'))
      return
    }

    var s = board.summary || {}
    var day =
      (window.__ACTION_BOARD__ && window.__ACTION_BOARD__.day) ||
      (board.items && board.items[0] && board.items[0].day) ||
      '—'
    meta.textContent = day + ' · 共 ' + (s.total || 0) + ' 条 · 只读公开'

    if (accent === 'patch') {
      sum.appendChild(sumCard('is-p0', String(s.p0 || 0), 'P0 紧急修复'))
      sum.appendChild(sumCard('is-todo', String(s.p1_p2 || 0), 'P1/P2 待办'))
      sum.appendChild(
        sumCard('is-ok', String((s.completion_rate || 0) + '%'), '完成率 · 已闭环 ' + (s.done || 0)),
      )
    } else {
      var lines = Object.keys(s.by_line || {}).length
      sum.appendChild(sumCard('is-blue', String(s.total || 0), '更新条目'))
      sum.appendChild(sumCard('is-todo', String(lines), '覆盖产线'))
      sum.appendChild(
        sumCard('is-ok', String((s.completion_rate || 0) + '%'), '完成率 · 已落 ' + (s.done || 0)),
      )
    }

    var items = board.items || []
    if (!items.length) {
      list.appendChild(el('div', 'progress-empty', '今日暂无条目（日更 digest 后自动刷新）。'))
      return
    }

    items.forEach(function (it) {
      var done = it.status === 'merged' || it.status === 'closed'
      var pri = done ? 'ok' : String(it.priority || 'P2').toLowerCase()
      var priLabel = done ? '已闭环' : String(it.priority || 'P2')
      var article = el('article', 'progress-item' + (done ? ' is-done' : ''))
      article.appendChild(el('span', 'progress-pri ' + pri, priLabel))
      var body = el('div')
      body.appendChild(el('h2', '', it.title || ''))
      var itemMeta = el('div', 'progress-item-meta')
      itemMeta.appendChild(el('span', '', it.line_label || it.line || '—'))
      itemMeta.appendChild(el('span', '', it.owner || 'AI 员工'))
      body.appendChild(itemMeta)
      article.appendChild(body)
      article.appendChild(el('span', 'progress-status', it.status_label || it.status || ''))
      list.appendChild(article)
    })
  }

  function boot() {
    var boardKey = document.body.getAttribute('data-board') || 'breakpoints'
    var accent = document.body.getAttribute('data-accent') || 'patch'
    fetch('/download-action-board.json', { cache: 'no-store' })
      .then(function (r) {
        var ct = r.headers.get('content-type') || ''
        return r.ok && ct.indexOf('json') >= 0 ? r.json() : null
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
