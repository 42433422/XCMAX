/* 能力目录交互：读取内嵌目录数据，渲染 域→模块→功能 三级结构，支持搜索与筛选。
 * 所有计数均来自目录数据自动统计，页面不手写数字。
 * 渲染使用 DOM API（createElement/textContent），不使用 innerHTML；URL 里拼接的 id 一律 encodeURIComponent。 */
;(function () {
  'use strict'

  var dataEl = document.getElementById('cap-catalog-data')
  if (!dataEl) return
  var DATA = JSON.parse(dataEl.textContent)
  var PLATFORM_LABELS = { windows: 'Windows 桌面', macos: 'macOS 桌面', web: 'Web', android: 'Android', ios: 'iOS' }
  var STATUS_LABELS = { verified: '已验证', partial: '部分验证', implemented: '已实现待验证', planned: '规划中' }
  var PLATFORM_STATUS_LABELS = { verified: '已验证', partial: '部分验证', pending: '待验证' }

  var qInput = document.getElementById('cap-q')
  var domSelect = document.getElementById('cap-domain')
  var statusSelect = document.getElementById('cap-status')
  var platformSelect = document.getElementById('cap-platform')
  var note = document.getElementById('cap-result-note')
  var tree = document.getElementById('cap-tree')

  function el(tag, className, text) {
    var node = document.createElement(tag)
    if (className) node.className = className
    if (text != null) node.textContent = text
    return node
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
    ;[qInput, domSelect, statusSelect, platformSelect].forEach(function (elm) {
      elm.addEventListener('input', render)
      elm.addEventListener('change', render)
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

  function featureRow(f) {
    var a = el('a', 'cap-feature-row')
    a.href = '/capabilities/feature/' + encodeURIComponent(f.id) + '.html'
    var left = el('div')
    left.appendChild(el('div', 'cap-feature-name', f.name))
    if (f.summary) left.appendChild(el('p', 'cap-feature-summary', f.summary))
    a.appendChild(left)
    var side = el('div', 'cap-feature-side')
    side.appendChild(el('span', 'cap-status st-' + f.status, STATUS_LABELS[f.status] || f.status))
    // 适用平台固定全列，每个平台带自己的状态；缺证据的平台显示「待验证」，不隐藏。
    var psById = {}
    ;(f.platform_status || []).forEach(function (ps) { psById[ps.id] = ps })
    ;(f.platforms || []).forEach(function (p) {
      var ps = psById[p]
      var st = ps ? ps.status : 'pending'
      side.appendChild(el('span', 'cap-platform cap-platform--' + st,
        (PLATFORM_LABELS[p] || p) + ' · ' + (PLATFORM_STATUS_LABELS[st] || st)))
    })
    a.appendChild(side)
    return a
  }

  function render() {
    var ft = currentFilters()
    var total = 0
    while (tree.firstChild) tree.removeChild(tree.firstChild)
    DATA.domains.forEach(function (d) {
      if (ft.domain && d.id !== ft.domain) return
      var domSec = el('section', 'cap-dom')
      var domCount = 0
      var head = el('div', 'cap-dom-head')
      head.appendChild(el('h3', null, d.name))
      head.appendChild(el('span', 'cap-dom-count', d.description || ''))
      domSec.appendChild(head)
      d.modules.forEach(function (m) {
        var modBox = el('div', 'cap-module')
        var modName = el('div', 'cap-module-name', m.name)
        var hasRows = false
        m.features.forEach(function (f) {
          var item = Object.assign({}, f, { module_name: m.name })
          if (!featureMatches(item, ft)) return
          modBox.appendChild(featureRow(f))
          hasRows = true
          domCount += 1
        })
        if (hasRows) {
          modBox.insertBefore(modName, modBox.firstChild)
          domSec.appendChild(modBox)
        }
      })
      if (domCount) {
        total += domCount
        tree.appendChild(domSec)
      }
    })
    if (total === 0) {
      tree.appendChild(el('p', 'cap-empty', '没有符合筛选条件的能力，请调整关键词或筛选。'))
    }
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
