/**
 * 世界意志 · AI 工作轨迹滚动条
 * 数据：/download-action-board.json → trajectory
 */
;(function () {
  'use strict'

  var FALLBACK = [
    { ts: '02:13', text: '考勤异常已标红，等待复核', href: '/download/breakpoints' },
    { ts: '07:10', text: '晨报已送达值班室', href: '/download/goals' },
    { ts: '08:15', text: 'P6 静默更新已完成并进入监控', href: '/download/goals' },
    { ts: '16:30', text: '断点清单有待闭环项，已派发责任员工', href: '/download/breakpoints' },
  ]

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
  }

  function itemHtml(it) {
    var href = it.href || (it.kind === 'patch' ? '/download/breakpoints' : '/download/goals')
    return (
      '<a class="world-will__item" href="' +
      esc(href) +
      '">' +
      '<time class="world-will__ts">' +
      esc(it.ts || '—') +
      '</time>' +
      '<span class="world-will__text">' +
      esc(it.text || '') +
      '</span>' +
      '</a>'
    )
  }

  function render(items) {
    var list = items && items.length ? items : FALLBACK
    var railInner = list.map(itemHtml).join('')
    // 双份内容做无缝循环
    return (
      '<aside class="world-will" aria-label="世界意志 · AI 工作轨迹">' +
      '<div class="world-will__label" title="AI 工作轨迹实时滚动">' +
      '<span class="world-will__dot" aria-hidden="true"></span>' +
      '世界意志' +
      '</div>' +
      '<div class="world-will__track">' +
      '<div class="world-will__rail">' +
      railInner +
      railInner +
      '</div>' +
      '</div>' +
      '</aside>'
    )
  }

  function mount(html) {
    var header = document.querySelector('header.site-header')
    if (!header) return
    if (document.querySelector('.world-will')) return
    header.insertAdjacentHTML('afterend', html)
  }

  function boot(items) {
    mount(render(items))
  }

  function load() {
    fetch('/download-action-board.json', { cache: 'no-store' })
      .then(function (res) {
        if (!res.ok) throw new Error('board ' + res.status)
        return res.json()
      })
      .then(function (data) {
        var traj = (data && data.trajectory) || []
        boot(traj)
      })
      .catch(function () {
        boot(FALLBACK)
      })
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load)
  } else {
    load()
  }
})()
