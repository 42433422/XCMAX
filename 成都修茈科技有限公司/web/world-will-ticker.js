/**
 * 世界意志滚动条（可选挂载）。推荐使用独立页 /world-will。
 * 数据：/download-action-board.json → trajectory（真实条目；空则不造假）
 * 挂载：优先页面内 [data-world-will-mount]（首页「公开工作轨迹」区块），
 *       页面无挂载点时仍挂在 header 之后（可视化页保持顶部条）。
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
    var rail = items && items.length ? items.map(itemHtml).join('') : ''
    rail = rail
      ? rail + rail
      : '<span class="world-will__item"><span class="world-will__text">暂无公开轨迹 · 进入世界意志页查看</span></span>'
    return (
      '<aside class="world-will" aria-label="世界意志 · AI 工作轨迹">' +
      '<a class="world-will__label" href="/world-will" title="打开世界意志">' +
      '<span class="world-will__dot" aria-hidden="true"></span>世界意志</a>' +
      '<div class="world-will__track"><div class="world-will__rail">' +
      rail +
      '</div></div></aside>'
    )
  }

  function mount(html) {
    var slot = document.querySelector('[data-world-will-mount]')
    var header = document.querySelector('header.site-header')
    if (!(slot || header) || document.querySelector('.world-will')) return
    if (!slot) return header.insertAdjacentHTML('afterend', html)
    slot.insertAdjacentHTML('afterbegin', html)
    slot.querySelector('.world-will').classList.add('world-will--inline')
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
