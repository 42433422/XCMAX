/**
 * 世界意志滚动条（可选挂载）。推荐使用独立页 /world-will。
 * 数据：/download-action-board.json → trajectory（真实条目；空则不造假）
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

  function itemHtml(it) {
    var href = it.href || '/world-will'
    return (
      '<a class="world-will__item" href="' +
      esc(href) +
      '">' +
      '<time class="world-will__ts">' +
      esc(it.ts || '—') +
      '</time>' +
      '<span class="world-will__text">' +
      esc(it.text || it.title || '') +
      '</span>' +
      '</a>'
    )
  }

  function render(items) {
    if (!items || !items.length) {
      return (
        '<aside class="world-will" aria-label="世界意志 · AI 工作轨迹">' +
        '<a class="world-will__label" href="/world-will" title="打开世界意志">' +
        '<span class="world-will__dot" aria-hidden="true"></span>世界意志</a>' +
        '<div class="world-will__track"><div class="world-will__rail">' +
        '<span class="world-will__item"><span class="world-will__text">暂无公开轨迹 · 进入世界意志页查看</span></span>' +
        '</div></div></aside>'
      )
    }
    var railInner = items.map(itemHtml).join('')
    return (
      '<aside class="world-will" aria-label="世界意志 · AI 工作轨迹">' +
      '<a class="world-will__label" href="/world-will" title="打开世界意志">' +
      '<span class="world-will__dot" aria-hidden="true"></span>世界意志</a>' +
      '<div class="world-will__track"><div class="world-will__rail">' +
      railInner +
      railInner +
      '</div></div></aside>'
    )
  }

  function mount(html) {
    var header = document.querySelector('header.site-header')
    if (!header || document.querySelector('.world-will')) return
    header.insertAdjacentHTML('afterend', html)
  }

  function fetchBoard(url, wrapped) {
    return fetch(url, { cache: 'no-store' })
      .then(function (res) {
        if (!res.ok) throw new Error('board ' + res.status)
        return res.json()
      })
      .then(function (payload) {
        if (!wrapped) return payload
        if (!payload || payload.ok !== true || !payload.data) throw new Error('live board unavailable')
        return payload.data
      })
  }

  fetchBoard('/api/public/action-board', true)
    .catch(function () {
      return fetchBoard('/download-action-board.json', false)
    })
    .then(function (data) {
      mount(render((data && data.trajectory) || []))
    })
    .catch(function () {
      mount(render([]))
    })
})()
