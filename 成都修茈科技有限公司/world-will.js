/**
 * 世界意志 · XCMAX AI 公司大厅
 * 数据：/download-company-hall.json（编制 + 真实状态投影）
 * 回退：/download-action-board.json
 */
;(function () {
  'use strict'

  var STATE = { data: null, filter: 'all' }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
  }

  /** 前端二次脱敏：避免接口/回退板仍带出角色提示词 */
  function sanitizePublicFeedText(raw) {
    var s = String(raw == null ? '' : raw).replace(/\s+/g, ' ').trim()
    if (!s) return '（暂无公开摘要）'
    if (
      /你是|回复必须说人话|SYSTEM\s*PROMPT|事故处理小组的\s*scout|不要直接倾倒|你的任务是|内部字段或英文模板/i.test(
        s,
      )
    ) {
      var m = s.match(/事件类型[:：]\s*([a-z][a-z0-9_.-]{2,64})/i)
      if (m) return '事故巡检：处理事件 ' + m[1]
      return '岗位任务执行摘要（内部提示词已隐藏）'
    }
    return s
  }

  function fmtGen(iso) {
    if (!iso) return '—'
    try {
      var d = new Date(iso)
      if (isNaN(d.getTime())) return String(iso)
      return d.toLocaleString('zh-CN', { hour12: false })
    } catch {
      return String(iso)
    }
  }

  var PUBLIC_TIME_ZONE = 'Asia/Shanghai'

  function timeParts(date) {
    var parts = new Intl.DateTimeFormat('zh-CN', {
      timeZone: PUBLIC_TIME_ZONE,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).formatToParts(date)
    return parts.reduce(function (out, part) {
      if (part.type !== 'literal') out[part.type] = part.value
      return out
    }, {})
  }

  function fmtFeedStamp(item) {
    var raw = item && (item.occurred_at || item.updated_at)
    if (raw) {
      try {
        var date = new Date(raw)
        if (!isNaN(date.getTime())) {
          var value = timeParts(date)
          var now = timeParts(new Date())
          var eventDay = Date.UTC(Number(value.year), Number(value.month) - 1, Number(value.day))
          var today = Date.UTC(Number(now.year), Number(now.month) - 1, Number(now.day))
          var ageDays = Math.round((today - eventDay) / 86400000)
          var dayLabel = value.month + '-' + value.day
          if (ageDays === 0) dayLabel = '今天'
          if (ageDays === 1) dayLabel = '昨天'
          return {
            day: dayLabel,
            clock: value.hour + ':' + value.minute,
            datetime: String(raw),
            title:
              value.year +
              '-' +
              value.month +
              '-' +
              value.day +
              ' ' +
              value.hour +
              ':' +
              value.minute +
              '（北京时间）',
          }
        }
      } catch {
        // Fall through to legacy day + HH:MM fields.
      }
    }
    var fallbackDay = String((item && item.day) || '')
    return {
      day: fallbackDay ? fallbackDay.slice(5) : '日期未知',
      clock: String((item && item.ts) || '—'),
      datetime: '',
      title: (fallbackDay ? fallbackDay + ' ' : '') + String((item && item.ts) || '—'),
    }
  }

  function autonomyFreshness(iso) {
    if (!iso) return '更新时间未知'
    var stamp = new Date(iso).getTime()
    if (isNaN(stamp)) return '快照 ' + fmtGen(iso)
    var ageMinutes = Math.max(0, Math.round((Date.now() - stamp) / 60000))
    if (ageMinutes <= 15) return '15 分钟内同步'
    if (ageMinutes < 1440) return ageMinutes + ' 分钟前同步'
    return Math.floor(ageMinutes / 1440) + ' 天前同步（请以管理端为准）'
  }

  function element(tag, className, text) {
    var node = document.createElement(tag)
    if (className) node.className = className
    if (text != null) node.textContent = String(text)
    return node
  }

  function clearElement(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild)
  }

  function renderAutonomyUnavailable(message) {
    var meta = document.getElementById('autonomy-meta')
    var overall = document.getElementById('autonomy-overall')
    var grid = document.getElementById('autonomy-grid')
    var proof = document.getElementById('autonomy-proof')
    if (meta) meta.textContent = message || '自治证据快照暂不可用'
    if (overall) {
      clearElement(overall)
      overall.appendChild(element('strong', '', '—'))
      overall.appendChild(element('span', '', '不以演示数据代替'))
    }
    if (grid) {
      clearElement(grid)
      grid.appendChild(
        element('p', 'autonomy-empty', '等待管理端发布脱敏后的真实进度。')
      )
    }
    clearElement(proof)
  }

  function renderAutonomy(data) {
    var meta = document.getElementById('autonomy-meta')
    var overall = document.getElementById('autonomy-overall')
    var grid = document.getElementById('autonomy-grid')
    var proof = document.getElementById('autonomy-proof')
    var dimensions = Array.isArray(data.dimensions) ? data.dimensions : []
    if (!dimensions.length) {
      renderAutonomyUnavailable('快照缺少七项证据，不展示推测值。')
      return
    }
    if (meta) {
      meta.textContent =
        autonomyFreshness(data.generated_at) +
        ' · 与创始人管理端使用同一评分结果 · 内部审批和故障细节不公开'
    }
    if (overall) {
      clearElement(overall)
      overall.appendChild(element('strong', '', (data.overall_progress || 0) + '%'))
      overall.appendChild(
        element(
          'span',
          '',
          '距离目标还差 ' +
            (data.overall_remaining == null ? '—' : data.overall_remaining) +
            '%'
        )
      )
    }
    if (grid) {
      clearElement(grid)
      dimensions.forEach(function (item) {
        var progress = Math.max(0, Math.min(100, Number(item.progress) || 0))
        var status = String(item.status || 'early')
        if (['ready', 'approaching', 'building', 'early'].indexOf(status) < 0) status = 'early'
        var card = element('article', 'autonomy-card autonomy-card--' + status)
        var header = element('header')
        header.appendChild(element('span', '', item.label || ''))
        header.appendChild(element('strong', '', progress + '%'))
        card.appendChild(header)
        var track = element('div', 'autonomy-track')
        var fill = element('i')
        fill.style.width = progress + '%'
        track.appendChild(fill)
        card.appendChild(track)
        card.appendChild(
          element('p', '', '下一门槛：' + (item.next_gap || '继续积累运行证据'))
        )
        grid.appendChild(card)
      })
    }
    if (proof) {
      var labels = {
        runtime_fresh: '运行证据新鲜',
        active_gates_ok: '自治门禁通过',
        governance_ok: '治理健康',
        employee_workforce_ready: 'AI 员工真实在岗',
        deploy_verified: '生产部署已验证',
        paid_value_verified: '真实付费已验证',
        paid_delivery_verified: '付费与不可变交付已关联',
        customer_acceptance_verified: '客户明确验收已验证',
      }
      clearElement(proof)
      Object.keys(labels).forEach(function (key) {
        var ok = Boolean((data.proof || {})[key])
        proof.appendChild(
          element('span', ok ? 'is-ok' : '', (ok ? '✓ ' : '待证明 · ') + labels[key])
        )
      })
    }
  }

  function loadAutonomy() {
    return fetch('/download-founder-autonomy.json', { cache: 'no-store' })
      .then(function (res) {
        if (!res.ok) throw new Error('autonomy ' + res.status)
        return res.json()
      })
      .then(renderAutonomy)
      .catch(function () {
        renderAutonomyUnavailable('管理端尚未发布自治证据快照（未造假填充）。')
      })
  }

  function initial(name) {
    var s = String(name || '?').trim()
    return s ? s.charAt(0) : '?'
  }

  function presenceLabel(p) {
    if (p === 'working') return '工作中'
    if (p === 'alert') return '告警'
    return '编制待命'
  }

  function emptyBox(lines) {
    return (
      '<div class="ww-feed-empty">' +
      (lines || [])
        .map(function (line, i) {
          return '<p class="' + (i ? 'muted' : '') + '">' + line + '</p>'
        })
        .join('') +
      '</div>'
    )
  }

  function renderDots(emps) {
    return (emps || [])
      .slice(0, 18)
      .map(function (e) {
        return (
          '<span class="hall-dot hall-dot--' +
          esc(e.presence || 'idle') +
          '" title="' +
          esc(e.name) +
          ' · ' +
          esc(presenceLabel(e.presence)) +
          '"></span>'
        )
      })
      .join('')
  }

  function renderDepartments(depts) {
    var root = document.getElementById('hall-depts')
    if (!root) return
    root.innerHTML = (depts || [])
      .map(function (d) {
        var c = d.counts || {}
        return (
          '<button type="button" class="hall-dept" data-dept="' +
          esc(d.id) +
          '" style="--dept:' +
          esc(d.color || '#79c0ff') +
          '">' +
          '<header><strong>' +
          esc(d.label) +
          '</strong><span>' +
          esc(d.employee_count || 0) +
          ' 人编制</span></header>' +
          '<div class="hall-dots">' +
          renderDots(d.employees) +
          '</div>' +
          '<footer>' +
          '<span class="is-work">' +
          esc(c.working || 0) +
          ' 工作中</span>' +
          '<span class="is-alert">' +
          esc(c.alert || 0) +
          ' 告警</span>' +
          '<span class="is-idle">' +
          esc(c.idle || 0) +
          ' 待命</span>' +
          '</footer></button>'
        )
      })
      .join('')

    root.querySelectorAll('.hall-dept').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-dept')
        var panel = document.getElementById('hall-dept-detail')
        if (!panel) return
        var dept = (depts || []).find(function (x) {
          return x.id === id
        })
        if (!dept) return
        panel.hidden = false
        panel.innerHTML =
          '<div class="hall-detail-head" style="--dept:' +
          esc(dept.color) +
          '"><h2>' +
          esc(dept.label) +
          '</h2><button type="button" class="hall-close" id="hall-close">收起</button></div>' +
          '<div class="hall-emp-grid">' +
          (dept.employees || [])
            .map(function (e) {
              return (
                '<article class="hall-emp hall-emp--' +
                esc(e.presence) +
                '">' +
                '<div class="hall-avatar" style="--dept:' +
                esc(e.dept_color || dept.color) +
                '">' +
                esc(initial(e.name)) +
                '</div>' +
                '<div><h3>' +
                esc(e.name) +
                '</h3>' +
                '<p class="hall-emp-id">' +
                esc(e.employee_id) +
                '</p>' +
                '<p class="hall-emp-act">' +
                esc(e.activity || presenceLabel(e.presence)) +
                '</p>' +
                '<p class="hall-emp-meta">' +
                esc(presenceLabel(e.presence)) +
                ' · 未闭环 ' +
                esc(e.open_action_items || 0) +
                ' · 24h 执行 ' +
                esc(e.runs_24h || 0) +
                '</p></div></article>'
              )
            })
            .join('') +
          '</div>'
        var close = document.getElementById('hall-close')
        if (close) {
          close.addEventListener('click', function () {
            panel.hidden = true
            panel.innerHTML = ''
          })
        }
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      })
    })
  }

  function filteredFeed(feed) {
    var list = feed || []
    if (STATE.filter === 'alert') {
      return list.filter(function (f) {
        return (
          f.presence === 'alert' ||
          f.status === 'open' ||
          /P0|失败|告警/.test(String(f.status_label || f.text || ''))
        )
      })
    }
    if (STATE.filter === 'working') {
      return list.filter(function (f) {
        return f.presence === 'working' || f.status === 'in_progress' || f.status === 'dispatched'
      })
    }
    if (STATE.filter === 'idle') {
      return list.filter(function (f) {
        return f.presence === 'idle'
      })
    }
    return list
  }

  function renderFeed(data) {
    var el = document.getElementById('hall-feed')
    if (!el) return
    var feed = filteredFeed(data.feed || [])
    var day = data.day || '—'
    var last = data.last_activity
    var cadence = data.cadence || {}

    if (!feed.length) {
      var lines = ['今日（' + esc(day) + '）筛选下暂无公开行动轨迹']
      if (last && last.text) {
        lines.push(
          '最近一次公开活动：' +
            esc(last.day || day) +
            ' ' +
            esc(last.ts || '') +
            ' — ' +
            esc(last.employee_name || '') +
            ' · ' +
            esc(last.text),
        )
      } else {
        lines.push('最近一次快照：' + esc(fmtGen(data.generated_at)))
      }
      if (cadence.next_window) {
        lines.push('下次预计窗口：' + esc(cadence.next_window))
      }
      if (STATE.filter !== 'all') {
        var filterNames = { working: '工作中', alert: '告警', idle: '编制待命' }
        lines[0] =
          '当前筛选「' +
          esc(filterNames[STATE.filter] || STATE.filter) +
          '」下暂无条目（未造假填充）'
      }
      el.innerHTML = emptyBox(lines)
      return
    }

    el.innerHTML =
      '<ol class="hall-timeline">' +
      feed
        .map(function (f, idx) {
          var stamp = fmtFeedStamp(f)
          var preview = sanitizePublicFeedText(f.text || '')
          return (
            '<li class="hall-timeline-item hall-timeline-item--' +
            esc(f.presence || 'idle') +
            '">' +
            '<button type="button" class="hall-timeline-btn" data-feed-idx="' +
            idx +
            '" aria-label="查看动态详情">' +
            '<time' +
            (stamp.datetime ? ' datetime="' + esc(stamp.datetime) + '"' : '') +
            ' title="' +
            esc(stamp.title) +
            '"><span class="hall-timeline-day">' +
            esc(stamp.day) +
            '</span><span class="hall-timeline-clock">' +
            esc(stamp.clock) +
            '</span></time>' +
            '<span class="hall-timeline-dot" style="background:' +
            esc(f.dept_color || '#94a3b8') +
            '"></span>' +
            '<div><strong>' +
            esc(f.dept_label || '') +
            ' · ' +
            esc(f.employee_name || '') +
            '</strong>' +
            '<span class="hall-feed-status">' +
            esc(f.status_label || presenceLabel(f.presence)) +
            '</span>' +
            '<p>' +
            esc(preview) +
            '</p>' +
            '<span class="hall-feed-more">查看详情</span></div></button></li>'
          )
        })
        .join('') +
      '</ol>'

    if (!el._feedBound) {
      el._feedBound = true
      el.addEventListener('click', function (ev) {
        var btn = ev.target && ev.target.closest ? ev.target.closest('[data-feed-idx]') : null
        if (!btn || !el.contains(btn)) return
        var idx = Number(btn.getAttribute('data-feed-idx'))
        var list = filteredFeed((STATE.data && STATE.data.feed) || [])
        var item = list[idx]
        if (!item) return
        openFeedDetail(item)
      })
    }
  }

  function openFeedDetail(item) {
    var panel = document.getElementById('hall-feed-detail')
    if (!panel) return
    var stamp = fmtFeedStamp(item)
    var body = sanitizePublicFeedText(item.detail || item.text || '（暂无公开摘要）')
    var href = String(item.href || '').trim()
    var truncated =
      item.detail_truncated === true ||
      /…$/.test(body) ||
      String(item.source || '') === 'execution_metric'
    var linkHtml = ''
    if (href && href !== '/world-will' && href !== '/world-will.html') {
      linkHtml =
        '<p class="hall-feed-detail-link"><a href="' +
        esc(href) +
        '">打开关联看板 →</a></p>'
    }
    var noteHtml = truncated
      ? '<p class="hall-feed-detail-note">这不是完整任务原文。公开执行指标仅保留约 128 字任务摘要；内部提示词与完整执行日志不在官网展示。</p>'
      : ''
    panel.hidden = false
    panel.innerHTML =
      '<div class="hall-detail-head" style="--dept:' +
      esc(item.dept_color || '#94a3b8') +
      '"><h2>动态详情</h2>' +
      '<button type="button" class="hall-close" id="hall-feed-close">收起</button></div>' +
      '<p class="hall-feed-detail-meta">' +
      esc(stamp.title || stamp.day + ' ' + stamp.clock) +
      ' · ' +
      esc(item.dept_label || '') +
      ' · ' +
      esc(item.employee_name || '') +
      ' · ' +
      esc(item.status_label || presenceLabel(item.presence)) +
      '</p>' +
      '<p class="hall-feed-detail-body">' +
      esc(body) +
      '</p>' +
      noteHtml +
      linkHtml
    var close = document.getElementById('hall-feed-close')
    if (close) {
      close.addEventListener('click', function () {
        panel.hidden = true
        panel.innerHTML = ''
      })
    }
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  function renderBoardLists(data) {
    var board = data.board || {}
    var gEl = document.getElementById('hall-goals')
    var day = data.day || '—'
    var last = data.last_activity
    var cadence = data.cadence || {}

    function listOrEmpty(el, items, emptyTitle) {
      if (!el) return
      if (!items || !items.length) {
        var lines = [emptyTitle + '（' + esc(day) + '）']
        if (last && last.text) {
          lines.push('最近公开活动：' + esc(last.ts || '') + ' — ' + esc(last.text))
        }
        if (cadence.next_window) lines.push('下次预计窗口：' + esc(cadence.next_window))
        el.innerHTML = emptyBox(lines)
        return
      }
      el.innerHTML = items
        .map(function (it) {
          return (
            '<article class="ww-row">' +
            '<h3>' +
            esc(it.title || '') +
            '</h3>' +
            '<div class="ww-item-meta">' +
            '<span class="ww-badge">' +
            esc(it.status_label || it.status || '') +
            '</span>' +
            '<span>' +
            esc(it.owner || '') +
            '</span>' +
            '<span>' +
            esc(it.priority || '') +
            '</span>' +
            '</div></article>'
          )
        })
        .join('')
    }

    listOrEmpty(gEl, board.goals || [], '今日暂无公开工作目标')
  }

  function renderAiDriver(data) {
    var el = document.getElementById('hall-ai-driver')
    if (!el) return
    var driver = data.ai_driver || {}
    var quota = driver.quota || {}
    var state = driver.state || 'standby'
    var provider = driver.provider || '待选择'
    var model = driver.model || '暂无可用模型'
    var remaining = quota.remaining_percent
    var quotaText = '额度未知'
    if (remaining !== null && remaining !== undefined && remaining !== '') {
      quotaText = esc(remaining) + '%'
    } else if (quota.state === 'healthy') {
      quotaText = '正常'
    } else if (quota.state === 'warning') {
      quotaText = '预警'
    } else if (quota.state === 'exhausted') {
      quotaText = '已耗尽'
    }
    var stateClass = state === 'degraded' ? ' is-degraded' : state === 'driving' ? '' : ' is-standby'
    var checked = driver.last_checked_at ? fmtGen(driver.last_checked_at) : '尚无巡检时间'

    el.innerHTML =
      '<div class="ai-driver-card">' +
      '<div class="ai-driver-top"><div class="ai-driver-person">' +
      '<span class="ai-driver-avatar" aria-hidden="true">LLM</span><div><strong>' +
      esc(driver.name || 'LLM 运维工程师') +
      '</strong><span>' +
      esc(driver.employee_id || 'llm-ops-engineer') +
      '</span></div></div><span class="ai-driver-state' +
      stateClass +
      '">' +
      esc(driver.state_label || '待启动') +
      '</span></div>' +
      '<div class="ai-driver-route"><div><small>当前平台路由</small><strong>' +
      esc(provider) +
      ' · ' +
      esc(model) +
      '</strong></div><div class="ai-driver-quota"><small>' +
      esc(quota.visibility === 'exact' ? '精确可用额度' : '额度状态') +
      '</small><strong>' +
      quotaText +
      '</strong></div></div>' +
      '<p class="ai-driver-foot">' +
      esc(driver.last_action_label || '尚无巡检记录') +
      ' · 最近检查 ' +
      esc(checked) +
      '</p></div>'
  }

  function renderReport(data) {
    var el = document.getElementById('hall-report')
    if (!el) return
    var c = data.counts || {}
    var r = data.report || {}
    var b = data.board || {}
    var driver = data.ai_driver || {}
    var busiest = r.busiest_dept || {}
    var mvp = r.mvp || {}
    var pm = data.presence_model || {}
    el.innerHTML =
      '<div class="hall-report-grid">' +
      '<div><strong>' +
      esc(c.roster || 0) +
      '</strong><span>编制员工</span></div>' +
      '<div><strong>' +
      esc(c.working || 0) +
      '</strong><span>工作中</span></div>' +
      '<div><strong>' +
      esc(c.alert || 0) +
      '</strong><span>告警</span></div>' +
      '<div title="' +
      esc(pm.idle || '') +
      '"><strong>' +
      esc(c.idle || 0) +
      '</strong><span>编制待命</span></div>' +
      '<div><strong class="hall-report-driver">' +
      esc(driver.state_label || '待启动') +
      '</strong><span>AI 驾驶</span></div>' +
      '<div><strong>' +
      esc(b.goals_total || 0) +
      '</strong><span>工作目标</span></div>' +
      '</div>' +
      '<p class="hall-report-line">最忙部门：' +
      esc(busiest.label || '—') +
      '（工作中 ' +
      esc(busiest.working || 0) +
      ' / 告警 ' +
      esc(busiest.alert || 0) +
      '）</p>' +
      '<p class="hall-report-line">负载领先：' +
      esc(mvp.name || '—') +
      '（未闭环 ' +
      esc(mvp.open_action_items || 0) +
      ' · 24h 执行 ' +
      esc(mvp.runs_24h || 0) +
      '）</p>' +
      '<p class="hall-report-note">编制待命 = 编制表已注册、当日无公开活跃任务；含按需触发岗位，不是离线伪装。</p>'
  }

  function bindSumFilters() {
    var sum = document.getElementById('ww-sum')
    if (!sum || sum._bound) return
    sum._bound = true
    sum.addEventListener('click', function (ev) {
      var card = ev.target.closest('[data-filter]')
      if (!card) return
      var f = card.getAttribute('data-filter') || 'all'
      STATE.filter = STATE.filter === f ? 'all' : f
      sum.querySelectorAll('[data-filter]').forEach(function (el) {
        el.classList.toggle('is-active', el.getAttribute('data-filter') === STATE.filter)
      })
      if (STATE.data) renderFeed(STATE.data)
      var feedPanel = document.getElementById('hall-feed')
      if (feedPanel) feedPanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    })
  }

  function render(data) {
    STATE.data = data
    var cadence = data.cadence || {}
    var meta = document.getElementById('ww-meta')
    if (meta) {
      meta.innerHTML =
        '业务日 ' +
        esc(data.day || '—') +
        ' · 快照 ' +
        esc(fmtGen(data.generated_at)) +
        ' · 编制 ' +
        esc((data.counts || {}).roster || 0) +
        ' · ' +
        esc(cadence.label || '事件驱动快照') +
        ' <span class="ww-pulse" title="快照随 digest/派发/部署回写刷新，非秒级推流">● SNAPSHOT</span>'
    }
    var sum = document.getElementById('ww-sum')
    if (sum) {
      var c = data.counts || {}
      var pm = data.presence_model || {}
      sum.innerHTML =
        '<button type="button" class="ww-sum-card is-live" data-filter="all" title="显示全部动态"><strong>' +
        esc(c.roster || 0) +
        '</strong><span>编制员工</span></button>' +
        '<button type="button" class="ww-sum-card is-todo" data-filter="working" title="' +
        esc(pm.working || '') +
        '"><strong>' +
        esc(c.working || 0) +
        '</strong><span>真实工作中</span></button>' +
        '<button type="button" class="ww-sum-card is-p0" data-filter="alert" title="' +
        esc(pm.alert || '') +
        '"><strong>' +
        esc(c.alert || 0) +
        '</strong><span>告警</span></button>' +
        '<button type="button" class="ww-sum-card is-blue" data-filter="idle" title="' +
        esc(pm.idle || '') +
        '"><strong>' +
        esc(c.idle || 0) +
        '</strong><span>编制待命</span></button>'
      sum.querySelectorAll('[data-filter]').forEach(function (el) {
        el.classList.toggle('is-active', el.getAttribute('data-filter') === STATE.filter)
      })
    }
    bindSumFilters()
    renderDepartments(data.departments || [])
    renderFeed(data)
    renderBoardLists(data)
    renderAiDriver(data)
    renderReport(data)
  }

  function bootEmpty(msg) {
    var meta = document.getElementById('ww-meta')
    if (meta) meta.textContent = msg
    render({
      day: '—',
      generated_at: '',
      schema: 'unavailable',
      cadence: { label: '暂无快照', next_window: '等待 digest / 状态回写' },
      counts: { roster: 0, working: 0, alert: 0, idle: 0 },
      departments: [],
      feed: [],
      ai_driver: { state: 'standby', state_label: '待启动', quota: {} },
      board: { breakpoints: [], goals: [] },
      report: {},
      presence_model: {},
    })
  }

  function fetchHall(url, wrapped) {
    return fetch(url, { cache: 'no-store' }).then(function (res) {
      if (!res.ok) throw new Error('hall ' + res.status)
      return res.json()
    }).then(function (payload) {
      if (!wrapped) return payload
      if (!payload || payload.ok !== true || !payload.data) throw new Error('live hall unavailable')
      return payload.data
    })
  }

  function fetchBoard(url, wrapped) {
    return fetch(url, { cache: 'no-store' }).then(function (res) {
      if (!res.ok) throw new Error('board ' + res.status)
      return res.json()
    }).then(function (payload) {
      if (!wrapped) return payload
      if (!payload || payload.ok !== true || !payload.data) throw new Error('live board unavailable')
      return payload.data
    })
  }

  function loadHall() {
    return fetchHall('/api/public/company-hall', true)
    .catch(function () {
      return fetchHall('/download-company-hall.json', false)
    })
    .then(render)
    .catch(function () {
      return fetchBoard('/api/public/action-board', true)
        .catch(function () {
          return fetchBoard('/download-action-board.json', false)
        })
        .then(function (board) {
          var traj = board.trajectory || []
          render({
            day: board.day,
            generated_at: board.generated_at,
            schema: 'fallback-action-board',
            cadence: {
              label: '大厅投影暂不可用，已回退行动板',
              next_window: '通常每日 08:00–08:30 晨报编排窗口',
            },
            counts: {
              roster: '—',
              working: traj.filter(function (t) {
                return t.status !== 'merged' && t.status !== 'closed'
              }).length,
              alert: traj.filter(function (t) {
                return t.status === 'open'
              }).length,
              idle: 0,
            },
            departments: [],
            ai_driver: {
              employee_id: 'llm-ops-engineer',
              name: 'LLM 运维工程师',
              state: 'standby',
              state_label: '状态未知',
              last_action_label: '大厅投影回退到行动板，不推测驾驶状态',
              quota: {},
            },
            feed: traj.map(function (t) {
              return {
                ts: t.ts,
                day: t.day || board.day,
                occurred_at: t.updated_at,
                employee_name: t.owner,
                dept_label: t.line_label,
                dept_color: '#facc15',
                status_label: t.status_label,
                text: t.title || t.text,
                href: t.href,
                presence: t.status === 'open' ? 'alert' : 'working',
                status: t.status,
              }
            }),
            last_activity: traj[0]
              ? {
                  ts: traj[0].ts,
                  day: board.day,
                  employee_name: traj[0].owner,
                  text: traj[0].title || traj[0].text,
                }
              : null,
            board: {
              breakpoints_total: ((board.breakpoints || {}).summary || {}).total || 0,
              goals_total: ((board.goals || {}).summary || {}).total || 0,
              breakpoints: ((board.breakpoints || {}).items || []).slice(0, 12),
              goals: ((board.goals || {}).items || []).slice(0, 12),
            },
            report: {},
            presence_model: {
              idle: '编制待命说明见大厅完整投影',
            },
          })
        })
        .catch(function () {
          bootEmpty('公开大厅暂不可用（未造假数据）。')
        })
    })
  }

  loadHall()
  window.setInterval(loadHall, 60000)
  loadAutonomy()
  window.setInterval(loadAutonomy, 60000)
})()
