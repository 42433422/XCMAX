/* 能力目录交互：读取内嵌目录数据，渲染 域→模块→功能 三级结构，支持搜索与筛选。
 * 所有计数均来自目录数据自动统计，页面不手写数字。 */
;(function () {
  'use strict'

  var dataEl = document.getElementById('cap-catalog-data')
  if (!dataEl) return
  var DATA = JSON.parse(dataEl.textContent)
  var PLATFORM_LABELS = { windows: 'Windows 桌面', macos: 'macOS 桌面', web: 'Web', android: 'Android', ios: 'iOS' }
  var STATUS_LABELS = { verified: '已验证', partial: '部分验证', implemented: '已实现待验证', planned: '规划中' }

  var qInput = document.getElementById('cap-q')
  var domSelect = document.getElementById('cap-domain')
  var statusSelect = document.getElementById('cap-status')
  var platformSelect = document.getElementById('cap-platform')
  var note = document.getElementById('cap-result-note')
  var tree = document.getElementById('cap-tree')

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    })
  }

  function initFilters() {
    DATA.domains.forEach(function (d) {
      var opt = document.createElement('option')
      opt.value = d.id
      opt.textContent = d.name
      domSelect.appendChild(opt)
    })
    Object.keys(PLATFORM_LABELS).forEach(function (p) {
      var opt = document.createElement('option')
      opt.value = p
      opt.textContent = PLATFORM_LABELS[p]
      platformSelect.appendChild(opt)
    })
    var params = new URLSearchParams(location.search)
    var q = params.get('q')
    var domain = params.get('domain')
    var status = params.get('status')
    var platform = params.get('platform')
    if (q) qInput.value = q
    if (domain) domSelect.value = domain
    if (status) statusSelect.value = status
    if (platform) platformSelect.value = platform
    ;[qInput, domSelect, statusSelect, platformSelect].forEach(function (el) {
      el.addEventListener('input', render)
      el.addEventListener('change', render)
    })
  }

  function currentFilters() {
    return {
      q: qInput.value.trim().toLowerCase(),
      domain: domSelect.value,
      status: statusSelect.value,
      platform: platformSelect.value,
    }
  }

  function featureMatches(f, ft) {
    if (ft.status && f.status !== ft.status) return false
    if (ft.platform && (f.platforms || []).indexOf(ft.platform) === -1) return false
    if (ft.q) {
      var hay = (f.name + ' ' + (f.summary || '') + ' ' + (f.module_name || '')).toLowerCase()
      if (hay.indexOf(ft.q) === -1) return false
    }
    return true
  }

  function render() {
    var ft = currentFilters()
    var total = 0
    var html = ''
    DATA.domains.forEach(function (d) {
      if (ft.domain && d.id !== ft.domain) return
      var domHtml = ''
      var domCount = 0
      d.modules.forEach(function (m) {
        var rows = ''
        m.features.forEach(function (f) {
          var item = Object.assign({}, f, { module_name: m.name })
          if (!featureMatches(item, ft)) return
          domCount += 1
          rows +=
            '<a class="cap-feature-row" href="/capabilities/feature/' + esc(f.id) + '.html">' +
            '<div><div class="cap-feature-name">' + esc(f.name) + '</div>' +
            (f.summary ? '<p class="cap-feature-summary">' + esc(f.summary) + '</p>' : '') +
            '</div>' +
            '<div class="cap-feature-side">' +
            '<span class="cap-status st-' + esc(f.status) + '">' + (STATUS_LABELS[f.status] || esc(f.status)) + '</span>' +
            (f.platforms || []).map(function (p) {
              return '<span class="cap-platform">' + esc(PLATFORM_LABELS[p] || p) + '</span>'
            }).join('') +
            '</div></a>'
        })
        if (rows) {
          domHtml +=
            '<div class="cap-module"><div class="cap-module-name">' + esc(m.name) + '</div>' + rows + '</div>'
        }
      })
      if (domHtml) {
        total += domCount
        html +=
          '<section class="cap-dom"><div class="cap-dom-head"><h3>' + esc(d.name) + '</h3>' +
          '<span class="cap-dom-count">' + esc(d.description || '') + '</span></div>' + domHtml + '</section>'
      }
    })
    tree.innerHTML = html || '<p class="cap-empty">没有符合筛选条件的能力，请调整关键词或筛选。</p>'
    var scope = []
    if (ft.domain) scope.push('产品域「' + domSelect.options[domSelect.selectedIndex].text + '」')
    if (ft.status) scope.push('状态「' + STATUS_LABELS[ft.status] + '」')
    if (ft.platform) scope.push('平台「' + PLATFORM_LABELS[ft.platform] + '」')
    if (ft.q) scope.push('关键词「' + qInput.value.trim() + '」')
    note.textContent = '筛选结果：' + total + ' 项能力（目录共 ' + DATA.stats.total + ' 项，由数据自动统计）' +
      (scope.length ? '；当前条件：' + scope.join('、') : '')
  }

  initFilters()
  render()
})()
