/* 全景功能地图：读取内嵌目录数据（与 50 项核心能力摘要、能力目录页共用同一份 SSOT 数据源），
 * 渲染 产品域 → 模块 → 功能 三级可交互地图，支持 产品域/模块/状态/平台/关键词 筛选。
 * 全部计数、状态、进度均由目录数据自动统计，页面不手写数字，杜绝“摘要绿色、地图红色”的分裂。
 * 移动端（<=720px）自动纵向折叠（域名收成手风琴、模块下沉为独立分组），不做横向大图。
 * 渲染使用 DOM API（createElement/textContent），不使用 innerHTML；URL id 一律编码。 */
;(function () {
  'use strict'

  var dataEl = document.getElementById('cap-catalog-data')
  if (!dataEl) return
  var DATA = JSON.parse(dataEl.textContent)
  var PLATFORM_LABELS = { windows: 'Windows', macos: 'macOS', web: 'Web', android: 'Android', ios: 'iOS' }
  var STATUS_META = { verified: '已验证', partial: '部分验证', implemented: '已实现待验证', planned: '规划中' }
  var STATUS_CLS = { verified: 'st-verified', partial: 'st-partial', implemented: 'st-implemented', planned: 'st-planned' }

  var qInput = document.getElementById('cap-map-q')
  var domSelect = document.getElementById('cap-map-domain')
  var modSelect = document.getElementById('cap-map-module')
  var statusSelect = document.getElementById('cap-map-status')
  var platformSelect = document.getElementById('cap-map-platform')
  var result = document.getElementById('cap-map-result')
  var root = document.getElementById('cap-map')
  if (!qInput || !root) return

  var lastDomain = null
  var initialModule = ''

  function el(tag, className, text) {
    var node = document.createElement(tag)
    if (className) node.className = className
    if (text != null) node.textContent = text
    return node
  }
  function link(feature, className, text) {
    var a = el('a', className, text)
    a.href = '/capabilities/feature/' + encodeURIComponent(feature.id) + '.html'
    return a
  }
  function badge(feature) {
    var s = el('span', 'cap-status ' + (STATUS_CLS[feature.status] || ''), STATUS_META[feature.status] || feature.status)
    return s
  }
  function plats(feature) {
    var wrap = el('span', 'cap-map-plats')
    ;(feature.platforms || []).forEach(function (p) {
      var t = el('span', 'cap-platform', PLATFORM_LABELS[p] || p)
      wrap.appendChild(t)
    })
    return wrap
  }

  function initFilterOpts(domains) {
    domains.forEach(function (d) {
      var opt = document.createElement('option')
      opt.value = d.id
      opt.textContent = d.name + '（' + featureCountOf(d) + '）'
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
    if (domain && domSelect.querySelector('option[value="' + domain + '"]')) { domSelect.value = domain; lastDomain = domain }
    if (status) statusSelect.value = status
    if (platform) platformSelect.value = platform
    rebuildModuleOptions()
    if (params.get('module')) {
      initialModule = params.get('module')
      rebuildModuleOptions()
    }
    ;[qInput, domSelect, modSelect, statusSelect, platformSelect].forEach(function (elm) {
      elm.addEventListener('input', onFilterChange)
      elm.addEventListener('change', onFilterChange)
    })
  }

  function featureCountOf(d) {
    return d.modules.reduce(function (n, m) { return n + m.features.length }, 0)
  }
  function allModules(domains) {
    var out = []
    domains.forEach(function (d) {
      d.modules.forEach(function (m) {
        if (!out.some(function (x) { return x.id === m.id })) out.push({ id: m.id, name: m.name, domain: d.id })
      })
    })
    return out
  }

  function curFilters() {
    return {
      q: qInput.value.trim().toLowerCase(),
      domain: domSelect.value,
      module: modSelect.value,
      status: statusSelect.value,
      platform: platformSelect.value,
    }
  }
  // 模块过滤在渲染时已按「所属模块」外层剪枝，此处不再判断 module_id（明细行走内嵌数据，无该字段）。
  function matches(f, ft, domainId) {
    if (ft.domain && domainId !== ft.domain) return false
    if (ft.status && f.status !== ft.status) return false
    if (ft.platform && (f.platforms || []).indexOf(ft.platform) === -1) return false
    if (ft.q && (f.name + ' ' + (f.summary || '')).toLowerCase().indexOf(ft.q) === -1) return false
    return true
  }

  // 模块下拉随产品域联动：仅在域变化时重建选项，并保留仍然有效的模块选择。
  function rebuildModuleOptions() {
    var keep = modSelect.value || initialModule
    while (modSelect.firstChild) modSelect.removeChild(modSelect.firstChild)
    var allOpt = document.createElement('option')
    allOpt.value = ''
    allOpt.textContent = '全部模块'
    modSelect.appendChild(allOpt)
    allModules(DATA.domains).forEach(function (m) {
      if (domSelect.value === '' || m.domain === domSelect.value) {
        var opt = document.createElement('option')
        opt.value = m.id
        opt.textContent = m.name
        modSelect.appendChild(opt)
      }
    })
    modSelect.value = keep && modSelect.querySelector('option[value="' + keep + '"]') ? keep : ''
    initialModule = ''
  }

  function onFilterChange() {
    if (domSelect.value !== lastDomain) {
      lastDomain = domSelect.value
      rebuildModuleOptions()
    }
    render()
  }

  function render() {
    var ft = curFilters()
    var total = 0
    var visibleDomains = 0
    while (root.firstChild) root.removeChild(root.firstChild)
    DATA.domains.forEach(function (d) {
      var dFeats = []
      var dCount = 0
      ;(d.modules || []).forEach(function (m) {
        if (ft.module && m.id !== ft.module) return
        var mFeats = (m.features || []).filter(function (f) { return matches(f, ft, d.id) })
        if (!mFeats.length) return
        dFeats.push({ module: m, feats: mFeats })
        dCount += mFeats.length
      })
      if (!dFeats.length) return
      visibleDomains += 1
      total += dCount

      var dom = el('section', 'capm-map-dom')
      var domHead = el('button', 'capm-map-dom-head', undefined)
      domHead.type = 'button'
      domHead.setAttribute('aria-expanded', 'false')
      var domTitle = el('span', 'capm-map-dom-name', d.name)
      domTitle.appendChild(el('span', 'capm-map-dom-count', '（' + dCount + ' 项）'))
      domHead.appendChild(domTitle)
      dom.appendChild(domHead)

      var body = el('div', 'capm-map-dom-body')
      dFeats.forEach(function (entry) {
        var modBox = el('section', 'capm-map-mod')
        var modName = el('h3', 'capm-map-mod-name', entry.module.name)
        modName.appendChild(el('span', 'capm-map-mod-count', '（' + entry.feats.length + '）'))
        modBox.appendChild(modName)
        entry.feats.forEach(function (f) {
          var row = link(f, 'capm-map-feat', undefined)
          var lead = el('span', 'capm-map-feat-name', f.name)
          var core = el('span', 'capm-map-feat-core', undefined)
          if (typeof f.featured === 'boolean' && f.featured === false) {
            core.textContent = '明细'
          } else if (f.featured !== false) {
            core.textContent = '核心'
          }
          row.appendChild(lead)
          if (core.textContent) row.appendChild(core)
          row.appendChild(badge(f))
          row.appendChild(plats(f))
          modBox.appendChild(row)
        })
        body.appendChild(modBox)
      })
      dom.appendChild(body)
      domHead.addEventListener('click', function () {
        var open = body.classList.toggle('open')
        domHead.setAttribute('aria-expanded', String(open))
      })
      root.appendChild(dom)
    })
    if (total === 0) {
      root.appendChild(el('p', 'cap-empty', '没有符合筛选条件的功能，请调整关键词或筛选。'))
      result.textContent = '匹配 0 项'
      return
    }
    result.textContent = '共匹配 ' + total + ' 项功能、' + visibleDomains + ' 个产品域。'
  }

  initFilterOpts(DATA.domains)
  onFilterChange()
})()