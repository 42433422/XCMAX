/**
 * 官网联系页 · 用户视角分步问卷（约 3–5 分钟）
 */
async function ensureCsrfCookie() {
  try {
    const res = await fetch('/api/health', { credentials: 'same-origin' })
    return res.ok
  } catch {
    return false
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  const form = document.getElementById('contact-form')
  if (!form || form.dataset.intakeWizard !== 'true') return

  const STEPS = [
    { id: 'profile', label: '认识您' },
    { id: 'problem', label: '您的困扰' },
    { id: 'workflow', label: '日常事务' },
    { id: 'contact', label: '联系方式' },
    { id: 'plan', label: '计划' },
    { id: 'review', label: '提交' },
  ]

  const state = {
    userRole: '',
    industry: '',
    roleSummary: '',
    primaryGoal: '',
    directions: [],
    manualSteps: '',
    painGoals: '',
    sampleDesc: '',
    name: '',
    phone: '',
    email: '',
    company: '',
    timeline: '',
    budget: '',
    needIntegration: '',
    integrationNote: '',
    extraNote: '',
  }

  let stepIndex = 0
  const csIntake = { active: false, uid: null, token: '' }

  const progressFill = document.getElementById('intake-progress-fill')
  const stepNodes = document.querySelectorAll('.intake-progress-step')
  const panelNodes = form.querySelectorAll('.intake-step-panel')
  const checklistItems = document.querySelectorAll('[data-intake-check]')
  const btnPrev = document.getElementById('intake-btn-prev')
  const btnNext = document.getElementById('intake-btn-next')
  const btnSubmit = document.getElementById('submit-btn')
  const apiError = document.getElementById('form-api-error')
  const success = document.getElementById('form-success')
  const reviewBody = document.getElementById('intake-review-body')
  const banner = document.getElementById('cs-intake-banner')
  function readCookie(name) {
    const parts = (`; ${document.cookie}`).split(`; ${name}=`)
    if (parts.length === 2) return parts.pop().split(';').shift() || ''
    return ''
  }

  function decodeBriefParam(raw) {
    const s = (raw || '').trim().replace(/-/g, '+').replace(/_/g, '/')
    const pad = '='.repeat((4 - (s.length % 4)) % 4)
    try {
      return decodeURIComponent(escape(atob(s + pad)))
    } catch {
      return ''
    }
  }

  function applyCsIntakeFromUrl() {
    const q = new URLSearchParams(window.location.search)
    const uid = Number(q.get('cs_uid'))
    const token = (q.get('cs_t') || '').trim()
    if (!Number.isFinite(uid) || uid <= 0 || !token) return
    csIntake.active = true
    csIntake.uid = uid
    csIntake.token = token
    if (banner) banner.hidden = false
    const brief = decodeBriefParam(q.get('brief') || '')
    const csName = (q.get('cs_name') || '').trim()
    if (csName) state.name = csName
    if (brief) state.extraNote = brief
    syncFieldsFromState()
  }

  function selectedRadio(name) {
    const el = form.querySelector(`input[name="${name}"]:checked`)
    return el ? String(el.value || '').trim() : ''
  }

  function syncStateFromFields() {
    state.userRole = selectedRadio('userRole')
    state.industry = (form.elements.industry?.value || '').trim()
    state.roleSummary = (form.elements.roleSummary?.value || '').trim()
    state.primaryGoal = selectedRadio('primaryGoal')
    state.directions = Array.from(form.querySelectorAll('input[name="direction"]:checked')).map((el) => el.value)
    state.name = (form.elements.name?.value || '').trim()
    state.phone = (form.elements.phone?.value || '').trim()
    state.email = (form.elements.email?.value || '').trim()
    state.company = (form.elements.company?.value || '').trim()
    state.sampleDesc = (form.elements.sampleDesc?.value || '').trim()
    state.manualSteps = (form.elements.manualSteps?.value || '').trim()
    state.painGoals = (form.elements.painGoals?.value || '').trim()
    state.timeline = (form.elements.timeline?.value || '').trim()
    state.budget = (form.elements.budget?.value || '').trim()
    state.needIntegration = (form.elements.needIntegration?.value || '').trim()
    state.integrationNote = (form.elements.integrationNote?.value || '').trim()
    state.extraNote = (form.elements.extraNote?.value || '').trim()
  }

  function syncFieldsFromState() {
    form.querySelectorAll('input[name="userRole"]').forEach((el) => {
      el.checked = el.value === state.userRole
    })
    form.querySelectorAll('input[name="primaryGoal"]').forEach((el) => {
      el.checked = el.value === state.primaryGoal
    })
    form.querySelectorAll('input[name="direction"]').forEach((el) => {
      el.checked = state.directions.includes(el.value)
    })
    if (form.elements.industry) form.elements.industry.value = state.industry
    if (form.elements.roleSummary) form.elements.roleSummary.value = state.roleSummary
    if (form.elements.name) form.elements.name.value = state.name
    if (form.elements.phone) form.elements.phone.value = state.phone
    if (form.elements.email) form.elements.email.value = state.email
    if (form.elements.company) form.elements.company.value = state.company
    if (form.elements.sampleDesc) form.elements.sampleDesc.value = state.sampleDesc
    if (form.elements.manualSteps) form.elements.manualSteps.value = state.manualSteps
    if (form.elements.painGoals) form.elements.painGoals.value = state.painGoals
    if (form.elements.timeline) form.elements.timeline.value = state.timeline
    if (form.elements.budget) form.elements.budget.value = state.budget
    if (form.elements.needIntegration) form.elements.needIntegration.value = state.needIntegration
    if (form.elements.integrationNote) form.elements.integrationNote.value = state.integrationNote
    if (form.elements.extraNote) form.elements.extraNote.value = state.extraNote
  }

  function setError(name, msg) {
    const node = document.getElementById(`${name}-error`)
    if (node) node.textContent = msg || ''
  }

  function validateProfile() {
    syncStateFromFields()
    let ok = true
    if (!state.userRole) {
      setError('userRole', '请选择最接近您的一项')
      ok = false
    } else setError('userRole', '')
    if (!state.roleSummary || state.roleSummary.length < 4) {
      setError('roleSummary', '请再写几句您平时主要在忙什么（至少 4 个字）')
      ok = false
    } else setError('roleSummary', '')
    return ok
  }

  function validateProblem() {
    syncStateFromFields()
    if (!state.primaryGoal) {
      setError('primaryGoal', '请选择最贴近您的一项')
      return false
    }
    setError('primaryGoal', '')
    return true
  }

  function validateWorkflow() {
    syncStateFromFields()
    let ok = true
    if (!state.manualSteps || state.manualSteps.length < 6) {
      setError('manualSteps', '请简单写一下现在怎么做事')
      ok = false
    } else setError('manualSteps', '')
    if (!state.painGoals || state.painGoals.length < 4) {
      setError('painGoals', '请写一下哪一步最费劲')
      ok = false
    } else setError('painGoals', '')
    return ok
  }

  function validateContact() {
    syncStateFromFields()
    let ok = true
    if (!state.name) {
      setError('name', '请输入姓名')
      ok = false
    } else setError('name', '')
    if (state.phone && !/^1[3-9]\d{9}$/.test(state.phone)) {
      setError('phone', '请输入有效的手机号码')
      ok = false
    } else setError('phone', '')
    if (!state.email) {
      setError('email', '请输入邮箱')
      ok = false
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(state.email)) {
      setError('email', '请输入有效的邮箱地址')
      ok = false
    } else setError('email', '')
    return ok
  }

  function validatePlan() {
    syncStateFromFields()
    let ok = true
    if (!state.timeline) {
      setError('timeline', '请选择大概什么时候需要')
      ok = false
    } else setError('timeline', '')
    if (!state.needIntegration) {
      setError('needIntegration', '请选择是否需要和现有系统连起来')
      ok = false
    } else setError('needIntegration', '')
    if (state.needIntegration === 'yes' && !state.integrationNote.trim()) {
      setError('integrationNote', '请简单写一下要对接什么系统')
      ok = false
    } else setError('integrationNote', '')
    return ok
  }

  const validators = {
    profile: validateProfile,
    problem: validateProblem,
    workflow: validateWorkflow,
    contact: validateContact,
    plan: validatePlan,
    review: () => true,
  }

  function buildMessage() {
    syncStateFromFields()
    const integration =
      state.needIntegration === 'yes'
        ? `需要 — ${state.integrationNote || '（待补充）'}`
        : state.needIntegration === 'no'
          ? '暂不需要'
          : '—'
    const dirs = state.directions.length ? state.directions.join('、') : '（未勾选）'
    return [
      '【修茈科技 · 客户需求问卷】',
      '',
      '■ 您是做什么的',
      `岗位角色：${state.userRole || '—'}`,
      `行业/业务：${state.industry || '—'}`,
      `日常在忙：${state.roleSummary}`,
      '',
      '■ 眼下最头疼的',
      `最想改善：${state.primaryGoal || '—'}`,
      `期望方向（可多选）：${dirs}`,
      '',
      '■ 现在怎么做事',
      `流程步骤：${state.manualSteps}`,
      `最费时间/易出错：${state.painGoals}`,
      `样例说明：${state.sampleDesc || '（未填，可回访再发）'}`,
      '',
      '■ 联系方式',
      `姓名：${state.name}`,
      `手机：${state.phone || '—'}`,
      `邮箱：${state.email}`,
      `公司：${state.company || '—'}`,
      '',
      '■ 时间与对接',
      `期望时间：${state.timeline || '—'}`,
      `预算：${state.budget || '暂未确定'}`,
      `系统对接：${integration}`,
      '',
      '■ 补充',
      state.extraNote || '—',
    ].join('\n')
  }

  function renderReview() {
    if (!reviewBody) return
    syncStateFromFields()
    const integration =
      state.needIntegration === 'yes'
        ? `需要 — ${state.integrationNote || '待补充'}`
        : '不需要'
    const rows = [
      ['您的角色', state.userRole || '—'],
      ['行业/业务', state.industry || '—'],
      ['日常在忙', state.roleSummary],
      ['最想改善', state.primaryGoal || '—'],
      ['期望方向', state.directions.join('、') || '—'],
      ['现在怎么做', state.manualSteps],
      ['最费劲的一步', state.painGoals],
      ['姓名', state.name],
      ['手机', state.phone || '—'],
      ['邮箱', state.email],
      ['公司', state.company || '—'],
      ['期望时间', state.timeline || '—'],
      ['预算', state.budget || '暂未确定'],
      ['系统对接', integration],
    ]
    reviewBody.innerHTML = rows
      .map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(v)}</dd>`)
      .join('')
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
  }

  /** 与 Modstore `_format_contact_audit_code` 一致；API 未带 audit_code 时用 id 兜底 */
  function formatContactAuditCode(submissionId) {
    const sid = Math.max(0, parseInt(String(submissionId), 10) || 0)
    if (!sid) return ''
    return `XC-${String(sid).padStart(6, '0')}`
  }

  function auditCodeFromSubmitResponse(data) {
    if (!data || typeof data !== 'object') return ''
    const direct = String(data.audit_code || data.auditCode || '').trim()
    if (direct) return direct
    return formatContactAuditCode(data.id)
  }

  function showContactSubmitSuccess(auditCode) {
    if (!success) return
    success.removeAttribute('hidden')
    if (auditCode) {
      success.innerHTML = `提交成功。您的需求审核码为 <strong class="intake-audit-code">${escapeHtml(auditCode)}</strong>，请保存以便查询进度；顾问也会在 1 个工作日内通过邮箱或电话与您联系。`
    } else {
      success.textContent =
        '提交成功。我们已收到您的需求，顾问会在 1 个工作日内通过邮箱或电话与您联系；若页面未显示审核码，请刷新后重试或联系客服。'
    }
    success.classList.add('visible')
  }

  function updateChecklist() {
    syncStateFromFields()
    const done = {
      profile: !!state.userRole && state.roleSummary.length >= 4,
      problem: !!state.primaryGoal,
      workflow: state.manualSteps.length >= 6 && state.painGoals.length >= 4,
      contact: !!state.name && !!state.email,
      plan: !!state.timeline && !!state.needIntegration,
      review: stepIndex === STEPS.length - 1,
    }
    checklistItems.forEach((el) => {
      const key = el.getAttribute('data-intake-check')
      const isDone = Boolean(done[key])
      el.classList.toggle('is-done', isDone)
      const icon = el.querySelector('.intake-check-icon')
      if (icon) icon.textContent = isDone ? '✓' : '○'
    })
  }

  function updateUi() {
    const step = STEPS[stepIndex]
    const pct = ((stepIndex + 1) / STEPS.length) * 100
    if (progressFill) progressFill.style.width = `${pct}%`

    stepNodes.forEach((node, idx) => {
      node.classList.toggle('is-active', idx === stepIndex)
      node.classList.toggle('is-done', idx < stepIndex)
    })
    panelNodes.forEach((panel) => {
      panel.classList.toggle('is-active', panel.dataset.intakeStep === step.id)
    })

    const kickers = form.querySelectorAll('.intake-step-kicker')
    kickers.forEach((el) => {
      el.textContent = `第 ${stepIndex + 1} 题 / 共 ${STEPS.length} 题`
    })

    if (btnPrev) btnPrev.disabled = stepIndex === 0
    if (btnNext) {
      btnNext.hidden = stepIndex === STEPS.length - 1
      btnNext.style.display = stepIndex === STEPS.length - 1 ? 'none' : ''
    }
    if (btnSubmit) {
      const showSubmit = stepIndex === STEPS.length - 1
      btnSubmit.hidden = !showSubmit
      btnSubmit.style.display = showSubmit ? '' : 'none'
    }

    if (step.id === 'review') renderReview()
    updateChecklist()
    syncAiAssistUi()
  }

  function syncAiAssistUi() {
    const block = document.getElementById('intake-ai-assist')
    const btn = document.getElementById('intake-ai-assist-btn')
    const submitted = isSubmitted()
    if (block) block.classList.toggle('is-disabled', submitted)
    if (btn) btn.disabled = submitted
  }

  let companyMatchTimer = null
  let companyMatchSeq = 0
  let companyMatchCache = null
  let companyMatchInFlight = false
  /** 用户已点过「系统/业务类型」后，公司名变更会按最新全文重新匹配 */
  let companyMatchUnlocked = false
  /** 当前输入框关键词是否已发起过匹配（与输入框内容绑定，不随选定公司改变） */
  let companyMatchQuerySynced = ''
  /** 用户选定 / 确认的工商全称（仅展示在输入框下方，不写回输入框） */
  let companyResolvedName = ''

  function looksLikeFullCompanyLegalName(q) {
    return /(?:有限公司|有限责任公司|股份有限公司|集团有限公司)/.test(String(q || ''))
  }

  function companyMatchWarnText(q, payload) {
    if (payload?.web_error) {
      return '联网检索暂不可用，将按您填写的名称继续'
    }
    if (payload?.query_incomplete || !looksLikeFullCompanyLegalName(q)) {
      return '联网检索未找到公司全称，请补全后重试或继续手动填写'
    }
    return '联网检索未匹配到该公司，将按您填写的名称继续'
  }

  function companyMatchContinueHint(q, payload) {
    if (payload?.web_error) {
      return '可继续填写系统类型；请稍后重试联网核对'
    }
    if (!payload?.found) {
      return '可继续填写系统类型；补全公司全称后请再次点选系统类型'
    }
    return '可继续填写系统类型'
  }

  function applyCompanyToForm(name) {
    const val = (name || '').trim()
    if (!val) return
    state.company = val
    const main = document.getElementById('company')
    if (main) main.value = val
  }

  function getAiAssistCompanyName() {
    const typed = (document.getElementById('intake-ai-company')?.value || '').trim()
    return (companyResolvedName || typed).trim()
  }

  function setCompanyResolvedName(name) {
    const resolved = formatCompanyDisplayName(name)
    if (!resolved) return
    companyResolvedName = resolved
    setCompanyMatchResult('ok', { name: resolved })
    applyCompanyToForm(resolved)
  }

  function selectCompanyFromMatch(item, { exact = false } = {}) {
    const inputEl = document.getElementById('intake-ai-company')
    const listEl = document.getElementById('intake-ai-company-suggest')
    const picked = formatCompanyDisplayName(item?.name)
    if (!picked) return
    companyMatchQuerySynced = (inputEl?.value || '').trim()
    companyMatchCache = {
      ok: true,
      found: true,
      matched: { ...item, name: picked, exact: Boolean(exact) },
      suggestions: [{ ...item, name: picked, exact: Boolean(exact) }],
    }
    setCompanyResolvedName(picked)
    setCompanyMatchHint(
      exact ? '已选定公司，请继续填写系统类型' : '已选定相近名称，请继续填写系统类型',
      'ok',
    )
    if (listEl) {
      listEl.hidden = true
      listEl.innerHTML = ''
    }
    inputEl?.setAttribute('aria-expanded', 'false')
  }

  const COMPANY_SOURCE_MARKERS = [
    '爱企查',
    '启信宝',
    '企查查',
    '天眼查',
    '水滴信用',
    '百度百科',
    '百度知道',
    '企查猫',
    '利查查',
  ]

  function formatCompanyDisplayName(name) {
    let s = (name || '').trim()
    if (!s) return ''
    s = s.split(/\s*[-_|｜]\s*/)[0].trim()
    for (const marker of COMPANY_SOURCE_MARKERS) {
      if (s.endsWith(marker)) s = s.slice(0, -marker.length).replace(/[\s\-_|｜]+$/, '').trim()
    }
    return s.replace(/\s+/g, '').slice(0, 80)
  }

  function normalizeCompanyMatchPayload(data) {
    if (!data || typeof data !== 'object') return data
    const cleanItem = (item) => {
      if (!item || !item.name) return item
      return { ...item, name: formatCompanyDisplayName(item.name) }
    }
    const suggestions = []
    const seen = new Set()
    for (const raw of Array.isArray(data.suggestions) ? data.suggestions : []) {
      const item = cleanItem(raw)
      const key = item?.name || ''
      if (!key || seen.has(key)) continue
      seen.add(key)
      suggestions.push(item)
    }
    let matched = data.matched ? cleanItem(data.matched) : null
    if (matched?.name && !suggestions.some((s) => s.name === matched.name)) {
      suggestions.unshift(matched)
    }
    return { ...data, matched, suggestions }
  }

  function clearResultEl(el) {
    if (!el) return
    if (typeof el.replaceChildren === 'function') {
      el.replaceChildren()
      return
    }
    while (el.firstChild) el.removeChild(el.firstChild)
  }

  function setCompanyMatchHint(text, variant) {
    const statusEl = document.getElementById('intake-ai-company-status')
    if (!statusEl) return
    statusEl.textContent = text || ''
    statusEl.className = variant
      ? `intake-company-status intake-company-status--${variant}`
      : 'intake-company-status'
  }

  function setCompanyMatchResult(mode, detail) {
    const resultEl = document.getElementById('intake-ai-company-result')
    if (!resultEl) return
    clearResultEl(resultEl)
    if (!mode || mode === 'hidden') {
      resultEl.hidden = true
      resultEl.className = 'intake-company-result'
      return
    }
    resultEl.hidden = false
    if (mode === 'ok') {
      const name = formatCompanyDisplayName(detail?.name || '')
      if (!name) {
        setCompanyMatchResult('hidden')
        return
      }
      resultEl.className = 'intake-company-result intake-company-result--ok'
      const check = document.createElement('span')
      check.className = 'intake-company-result__check'
      check.setAttribute('aria-hidden', 'true')
      check.textContent = '✓'
      const nameEl = document.createElement('span')
      nameEl.className = 'intake-company-result__name'
      nameEl.textContent = name
      resultEl.append(check, nameEl)
      return
    }
    if (mode === 'warn') {
      resultEl.className = 'intake-company-result intake-company-result--warn'
      const label = document.createElement('span')
      label.className = 'intake-company-result__text'
      label.textContent = (detail?.text || '未匹配到工商名称').trim()
      resultEl.append(label)
    }
  }

  function renderCompanyMatchUi(data) {
    const statusEl = document.getElementById('intake-ai-company-status')
    const listEl = document.getElementById('intake-ai-company-suggest')
    const inputEl = document.getElementById('intake-ai-company')
    if (!statusEl || !listEl || !inputEl) return

    const q = (inputEl.value || '').trim()
    if (q.length < 2) {
      setCompanyMatchResult('hidden')
      setCompanyMatchHint('')
      listEl.hidden = true
      listEl.innerHTML = ''
      inputEl.setAttribute('aria-expanded', 'false')
      return
    }

    const payload = normalizeCompanyMatchPayload(data)
    companyMatchCache = payload
    const matched = payload?.matched
    const suggestions = Array.isArray(payload?.suggestions) ? payload.suggestions : []

    const multiPick = suggestions.length > 1
    if (matched?.name && !multiPick) {
      setCompanyResolvedName(matched.name)
      setCompanyMatchHint(
        payload?.web_used || matched.source === 'web'
          ? '已通过联网检索核对，请继续填写系统类型'
          : '已匹配，请继续填写系统类型',
        'ok',
      )
      listEl.hidden = true
      listEl.innerHTML = ''
      inputEl.setAttribute('aria-expanded', 'false')
      return
    }
    if (matched?.name && multiPick) {
      setCompanyMatchResult('hidden')
      companyResolvedName = ''
      setCompanyMatchHint('请从下方选择公司全称（搜索词仍保留在输入框）')
    } else if (!payload?.found) {
      companyResolvedName = ''
      setCompanyMatchResult('warn', { text: companyMatchWarnText(q, payload) })
      setCompanyMatchHint(companyMatchContinueHint(q, payload), 'new')
    } else {
      setCompanyMatchResult('hidden')
      setCompanyMatchHint('请选择下方匹配的公司名称')
    }

    listEl.innerHTML = ''
    if (!suggestions.length) {
      listEl.hidden = true
      inputEl.setAttribute('aria-expanded', 'false')
      return
    }

    suggestions.forEach((item) => {
      const li = document.createElement('li')
      const btn = document.createElement('button')
      btn.type = 'button'
      btn.setAttribute('role', 'option')
      btn.textContent = formatCompanyDisplayName(item.name)
      btn.addEventListener('click', () => {
        selectCompanyFromMatch(item, { exact: true })
      })
      li.appendChild(btn)
      listEl.appendChild(li)
    })
    listEl.hidden = false
    inputEl.setAttribute('aria-expanded', 'true')
  }

  async function runCompanyMatch(query) {
    const q = (query || '').trim()
    if (q.length < 2) {
      renderCompanyMatchUi(null)
      return
    }
    const seq = ++companyMatchSeq
    companyMatchInFlight = true
    setCompanyMatchResult('hidden')
    setCompanyMatchHint(`正在用「${q}」匹配公司名称…`)
    try {
      const res = await fetch(
        `/api/public/contact/companies/match?q=${encodeURIComponent(q)}&limit=8&web=true`,
        { credentials: 'same-origin' },
      )
      if (seq !== companyMatchSeq) return
      if (!res.ok) {
        if (res.status === 429) {
          setCompanyMatchResult('warn', { text: '匹配请求过于频繁' })
          setCompanyMatchHint('请等待约 1 分钟后再试，或继续手动填写', 'new')
          return
        }
        setCompanyMatchResult('warn', { text: '匹配服务暂时不可用' })
        setCompanyMatchHint(
          res.status === 404
            ? '当前页面未连上官网 API，请用 xiu-ci.com 打开联系页'
            : '请稍后重试或继续手动填写',
          'new',
        )
        return
      }
      const data = normalizeCompanyMatchPayload(await res.json())
      if (seq !== companyMatchSeq) return
      companyMatchQuerySynced = q
      renderCompanyMatchUi(data)
    } catch {
      if (seq !== companyMatchSeq) return
      setCompanyMatchResult('warn', { text: '无法连接匹配服务' })
      setCompanyMatchHint(
        location.protocol === 'file:'
          ? '本地预览无法匹配，请通过官网访问'
          : '网络异常，请稍后重试',
        'new',
      )
    } finally {
      if (seq === companyMatchSeq) companyMatchInFlight = false
    }
  }

  function clearCompanyMatchUi() {
    companyMatchCache = null
    companyMatchQuerySynced = ''
    companyResolvedName = ''
    setCompanyMatchResult('hidden')
    setCompanyMatchHint('')
    const listEl = document.getElementById('intake-ai-company-suggest')
    const inputEl = document.getElementById('intake-ai-company')
    if (listEl) {
      listEl.hidden = true
      listEl.innerHTML = ''
    }
    if (inputEl) inputEl.setAttribute('aria-expanded', 'false')
  }

  function readAiCompanyQuery() {
    return (document.getElementById('intake-ai-company')?.value || '').trim()
  }

  function scheduleCompanyMatch() {
    if (companyMatchTimer) window.clearTimeout(companyMatchTimer)
    companyMatchTimer = window.setTimeout(() => {
      companyMatchTimer = null
      const qNow = readAiCompanyQuery()
      if (qNow.length < 2) return
      if (qNow === companyMatchQuerySynced && companyMatchCache) {
        renderCompanyMatchUi(companyMatchCache)
        return
      }
      if (companyMatchInFlight) return
      void runCompanyMatch(qNow)
    }, 400)
  }

  function tryStartCompanyMatch() {
    if (readAiCompanyQuery().length < 2) return
    scheduleCompanyMatch()
  }

  const AI_FILL_STEP_LABELS = {
    profile: '认识您',
    problem: '您的困扰',
    workflow: '日常事务',
    contact: '联系方式',
    plan: '计划',
  }

  const AI_FILL_FIELD_PLAN = [
    { step: 'profile', key: 'userRole', kind: 'radio', name: 'userRole' },
    { step: 'profile', key: 'industry', kind: 'text', id: 'industry' },
    { step: 'profile', key: 'roleSummary', kind: 'textarea', id: 'roleSummary' },
    { step: 'problem', key: 'primaryGoal', kind: 'radio', name: 'primaryGoal' },
    { step: 'problem', key: 'directions', kind: 'checkbox', name: 'direction' },
    { step: 'workflow', key: 'manualSteps', kind: 'textarea', id: 'manualSteps' },
    { step: 'workflow', key: 'painGoals', kind: 'textarea', id: 'painGoals' },
    { step: 'workflow', key: 'sampleDesc', kind: 'textarea', id: 'sampleDesc', optional: true },
    { step: 'contact', key: 'company', kind: 'text', id: 'company' },
    { step: 'contact', key: 'name', kind: 'text', id: 'name', optional: true },
    { step: 'contact', key: 'phone', kind: 'text', id: 'phone', optional: true },
    { step: 'contact', key: 'email', kind: 'text', id: 'email', optional: true },
    { step: 'plan', key: 'timeline', kind: 'select', id: 'timeline' },
    { step: 'plan', key: 'budget', kind: 'select', id: 'budget', optional: true },
    { step: 'plan', key: 'needIntegration', kind: 'select', id: 'needIntegration' },
    { step: 'plan', key: 'integrationNote', kind: 'text', id: 'integrationNote', optional: true },
    { step: 'plan', key: 'extraNote', kind: 'textarea', id: 'extraNote', optional: true },
  ]

  function delay(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms))
  }

  function draftFieldHasValue(draft, key) {
    if (!draft || typeof draft !== 'object') return false
    if (key === 'directions') {
      return Array.isArray(draft.directions) && draft.directions.length > 0
    }
    return String(draft[key] ?? '').trim().length > 0
  }

  function applyDraftKeyToState(draft, key) {
    if (!draft || !(key in draft)) return
    const val = draft[key]
    if (key === 'directions') {
      state.directions = Array.isArray(val) ? val.map(String) : []
      return
    }
    if (typeof val === 'string' || typeof val === 'number') {
      state[key] = String(val).trim()
    }
  }

  function ensureAiFillOverlay() {
    const main = document.querySelector('.contact-intake-main')
    if (!main) return null
    let overlay = document.getElementById('intake-ai-fill-overlay')
    if (!overlay) {
      overlay = document.createElement('div')
      overlay.id = 'intake-ai-fill-overlay'
      overlay.className = 'intake-ai-fill-overlay'
      overlay.hidden = true
      overlay.setAttribute('aria-live', 'polite')
      overlay.innerHTML = `
        <div class="intake-ai-fill-overlay__panel">
          <div class="intake-ai-fill-overlay__spinner" aria-hidden="true"></div>
          <p class="intake-ai-fill-overlay__status">AI 正在预填问卷…</p>
          <div class="intake-ai-fill-overlay__track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
            <span class="intake-ai-fill-overlay__bar"></span>
          </div>
        </div>`
      main.appendChild(overlay)
    }
    return overlay
  }

  function setAiFillBusy(active, statusText, progressRatio) {
    const assist = document.getElementById('intake-ai-assist')
    const main = document.querySelector('.contact-intake-main')
    const overlay = ensureAiFillOverlay()
    const pct = Math.max(0, Math.min(1, Number(progressRatio) || 0))
    if (assist) assist.classList.toggle('contact-intake-ai--filling', active)
    if (main) main.classList.toggle('contact-intake-main--ai-filling', active)
    if (overlay) {
      overlay.hidden = !active
      const statusEl = overlay.querySelector('.intake-ai-fill-overlay__status')
      const bar = overlay.querySelector('.intake-ai-fill-overlay__bar')
      const track = overlay.querySelector('.intake-ai-fill-overlay__track')
      if (statusEl && statusText) statusEl.textContent = statusText
      if (bar) bar.style.width = `${Math.round(pct * 100)}%`
      if (track) track.setAttribute('aria-valuenow', String(Math.round(pct * 100)))
    }
  }

  function setAiAssistBtnLoading(loading, labelText) {
    const btn = document.getElementById('intake-ai-assist-btn')
    if (!btn) return
    const labelEl = btn.querySelector('.intake-ai-btn__label')
    btn.classList.toggle('is-ai-loading', loading)
    btn.disabled = loading || isSubmitted()
    if (labelEl && labelText) labelEl.textContent = labelText
  }

  function pulseAiField(el) {
    if (!el) return
    const wrap =
      el.closest('.form-field') ||
      el.closest('.intake-option-card') ||
      el.closest('fieldset') ||
      el.parentElement
    wrap?.classList.add('intake-field--ai-fill')
    el.classList.add('intake-field--highlight')
    window.setTimeout(() => {
      wrap?.classList.remove('intake-field--ai-fill')
      el.classList.remove('intake-field--highlight')
    }, 1600)
  }

  async function typeIntoField(el, text) {
    const full = String(text || '')
    if (!full) return
    el.classList.add('intake-field--ai-typing')
    const maxTyped = 140
    const typedPart = full.length > maxTyped ? full.slice(0, maxTyped) : full
    if ('value' in el) el.value = ''
    const chars = [...typedPart]
    for (let i = 0; i < chars.length; i++) {
      if ('value' in el) el.value += chars[i]
      if (i % 3 === 0) await delay(14)
      else await delay(8)
    }
    if (full.length > maxTyped && 'value' in el) {
      el.value = full
      await delay(80)
    }
    el.classList.remove('intake-field--ai-typing')
    pulseAiField(el)
  }

  async function animateDraftField(draft, item) {
    const val = draft[item.key]
    if (item.kind === 'radio') {
      const v = String(val || '').trim()
      const input = form.querySelector(`input[name="${item.name}"][value="${CSS.escape(v)}"]`)
      if (!input) return
      input.checked = true
      const card = input.closest('.intake-option-card')
      card?.classList.add('is-ai-pick')
      pulseAiField(input)
      await delay(220)
      card?.classList.remove('is-ai-pick')
      applyDraftKeyToState(draft, item.key)
      return
    }
    if (item.kind === 'checkbox') {
      const dirs = Array.isArray(val) ? val.map(String) : []
      form.querySelectorAll(`input[name="${item.name}"]`).forEach((el) => {
        el.checked = false
      })
      for (const d of dirs) {
        const input = form.querySelector(`input[name="${item.name}"][value="${CSS.escape(d)}"]`)
        if (!input) continue
        input.checked = true
        input.closest('.intake-chip')?.classList.add('is-ai-pick')
        await delay(120)
        input.closest('.intake-chip')?.classList.remove('is-ai-pick')
      }
      applyDraftKeyToState(draft, item.key)
      pulseAiField(form.querySelector(`input[name="${item.name}"]`))
      await delay(180)
      return
    }
    const el = item.id ? document.getElementById(item.id) : null
    if (!el) return
    if (item.kind === 'select') {
      el.value = String(val || '').trim()
      el.dispatchEvent(new Event('change', { bubbles: true }))
      applyDraftKeyToState(draft, item.key)
      pulseAiField(el)
      await delay(260)
      return
    }
    applyDraftKeyToState(draft, item.key)
    await typeIntoField(el, state[item.key] || String(val || ''))
  }

  async function animateDraftFill(draft, onProgress) {
    const items = AI_FILL_FIELD_PLAN.filter((item) => {
      if (item.optional && !draftFieldHasValue(draft, item.key)) return false
      return draftFieldHasValue(draft, item.key)
    })
    if (!items.length) {
      mergeDraftIntoState(draft)
      syncFieldsFromState()
      updateChecklist()
      updateUi()
      return
    }

    let stepCursor = ''
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      const ratio = 0.12 + (0.86 * (i + 1)) / items.length
      if (item.step !== stepCursor) {
        stepCursor = item.step
        goToStepById(item.step)
        const stepLabel = AI_FILL_STEP_LABELS[item.step] || item.step
        onProgress?.(`正在填写「${stepLabel}」…`, ratio - 0.04)
        await delay(320)
      }
      await animateDraftField(draft, item)
      syncFieldsFromState()
      updateChecklist()
      updateUi()
      onProgress?.(`正在填写「${AI_FILL_STEP_LABELS[item.step] || item.step}」…`, ratio)
      await delay(100)
    }

    mergeDraftIntoState(draft)
    syncFieldsFromState()
    updateChecklist()
    updateUi()

    const main = document.querySelector('.contact-intake-main')
    main?.classList.add('contact-intake-main--ai-done')
    window.setTimeout(() => main?.classList.remove('contact-intake-main--ai-done'), 1200)
    goToStepById(inferEarliestIncompleteStep(state))
    scrollIntakeWizardToTop()
  }

  function inferEarliestIncompleteStep(s) {
    const order = ['profile', 'problem', 'workflow', 'contact', 'plan', 'review']
    for (const id of order) {
      if (id === 'profile' && (!s.userRole?.trim() || !s.roleSummary?.trim())) return id
      if (id === 'problem' && !s.primaryGoal?.trim()) return id
      if (id === 'workflow' && (!s.manualSteps?.trim() || !s.painGoals?.trim())) return id
      if (id === 'contact' && (!s.name?.trim() || !s.email?.trim())) return id
      if (id === 'plan' && (!s.timeline?.trim() || !s.needIntegration?.trim())) return id
    }
    return 'review'
  }

  function mergeDraftIntoState(partial) {
    if (!partial || typeof partial !== 'object') return
    const allowed = Object.keys(state)
    for (const key of allowed) {
      if (!(key in partial)) continue
      const val = partial[key]
      if (key === 'directions') {
        state.directions = Array.isArray(val) ? val.map(String) : []
      } else if (typeof val === 'string' || typeof val === 'number') {
        state[key] = String(val).trim()
      }
    }
  }

  async function runAiIntakeFill(prompt) {
    setAiFillBusy(true, 'AI 正在分析企业与系统场景…', 0.08)
    await ensureCsrfCookie()
    const csrf = readCookie('csrf_token')
    const headers = { 'Content-Type': 'application/json', Accept: 'application/json' }
    if (csrf) headers['X-CSRF-Token'] = csrf
    syncStateFromFields()
    setAiFillBusy(true, '正在生成问卷草稿…', 0.22)
    const res = await fetch('/api/agent/butler/corp-intake-fill', {
      method: 'POST',
      credentials: 'same-origin',
      headers,
      body: JSON.stringify({
        message: prompt,
        current_draft: { ...state, directions: [...state.directions] },
      }),
    })
    if (!res.ok) {
      let msg = '智能预填暂时不可用，请稍后重试或手动填写。'
      if (res.status === 429) msg = '请求过于频繁，请约 1 分钟后再试。'
      else if (res.status === 403) msg = '页面会话已过期，请刷新页面（Cmd+Shift+R）后重试。'
      else if (res.status === 503) {
        try {
          const err = await res.json()
          if (err?.detail) msg = String(err.detail)
        } catch {
          /* ignore */
        }
      }
      setAiFillBusy(false)
      return { ok: false, message: msg }
    }
    let data = {}
    try {
      data = await res.json()
    } catch {
      setAiFillBusy(false)
      return { ok: false, message: '预填结果解析失败，请手动填写。' }
    }
    const draft = data?.draft && typeof data.draft === 'object' ? data.draft : {}
    if (!Object.keys(draft).length) {
      setAiFillBusy(false)
      return {
        ok: false,
        message: (data?.reply || '').trim() || '未能生成可填内容，请补充描述后重试。',
      }
    }
    try {
      setAiFillBusy(true, '正在写入问卷…', 0.35)
      await animateDraftFill(draft, (status, ratio) => setAiFillBusy(true, status, ratio))
    } finally {
      setAiFillBusy(false)
    }
    const section = document.querySelector('.contact-intake-section')
    if (section) {
      const top = section.getBoundingClientRect().top + window.scrollY - 84
      window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
    }
    return { ok: true, message: (data?.reply || '').trim() || '已预填问卷，请核对修改。' }
  }

  async function executeAiAssistFill(typedCompany, system) {
    if (isSubmitted()) {
      return { ok: false, message: '问卷已提交，无法继续预填。' }
    }
    const companyEl = document.getElementById('intake-ai-company')
    const systemEl = document.getElementById('intake-ai-system')
    const c = String(typedCompany || '').trim()
    const s = String(system || '').trim()
    if (!c || !s) {
      return { ok: false, message: '请填写公司名称和系统 / 业务类型。' }
    }
    if (companyEl) companyEl.value = c
    if (systemEl) systemEl.value = s
    if (c !== companyMatchQuerySynced) {
      companyMatchCache = null
      companyMatchQuerySynced = ''
      companyResolvedName = ''
      setCompanyMatchResult('hidden')
    }
    if (!companyResolvedName && c.length >= 2 && c !== companyMatchQuerySynced) {
      await runCompanyMatch(c)
    }
    const finalCompany = getAiAssistCompanyName() || c
    const prompt = buildAiAssistPrompt(finalCompany, s)
    setAiAssistBtnLoading(true, '正在生成…')
    if (apiError) apiError.textContent = ''
    showAiAssistHint('AI 正在预填，请稍候…')
    try {
      const result = await runAiIntakeFill(prompt)
      if (result.ok) {
        showAiAssistHint(result.message)
        window.dispatchEvent(
          new CustomEvent('xc-corp-intake-assist', {
            detail: { message: prompt, prompt, company: finalCompany, system: s, filled: true },
          }),
        )
      } else {
        showAiAssistHint(result.message)
      }
      return result
    } catch {
      setAiFillBusy(false)
      const err = '网络异常，请稍后重试。'
      showAiAssistHint(err)
      return { ok: false, message: err }
    } finally {
      setAiAssistBtnLoading(false, 'AI 一键填好问卷')
    }
  }

  function buildAiAssistPrompt(company, system) {
    const lines = [
      `公司：${company}`,
      `主要系统/业务：${system}`,
    ]
    const matched = companyMatchCache?.matched
    const companyForPrompt = getAiAssistCompanyName() || company
    if (matched?.name && matched.name === companyForPrompt) {
      if (matched.has_history && matched.submission_count > 0) {
        lines.push(`该公司曾提交过需求 ${matched.submission_count} 次，请结合历史客户场景推断。`)
      } else if (matched.in_crm) {
        lines.push('该公司已在客户库中，请结合包装/贸易类企业典型场景推断。')
      }
    }
    lines.push(
      '',
      '请根据该公司与系统类型的典型业务场景，完整预填联系页需求问卷（岗位角色、行业、日常事务、困扰、流程步骤、改善方向、时间计划等可合理推断的项）。',
      `draft 中 company 填「${companyForPrompt}」。`,
      '不要编造手机、邮箱、姓名；联系方式留空，由用户自行填写。',
    )
    return lines.join('\n')
  }

  function showAiAssistHint(msg) {
    const hint = document.getElementById('intake-ai-assist-hint')
    if (!hint) return
    if (!msg) {
      hint.hidden = true
      hint.textContent = ''
      return
    }
    hint.hidden = false
    hint.textContent = msg
    if (apiError) apiError.textContent = ''
  }

  function initAiAssistEntry() {
    const btn = document.getElementById('intake-ai-assist-btn')
    const companyEl = document.getElementById('intake-ai-company')
    const systemEl = document.getElementById('intake-ai-system')
    if (!companyEl || !systemEl) return

    if (btn && !btn.querySelector('.intake-ai-btn__label')) {
      const defaultLabel = (btn.textContent || 'AI 一键填好问卷').trim()
      btn.textContent = ''
      const spin = document.createElement('span')
      spin.className = 'intake-ai-btn__spinner'
      spin.setAttribute('aria-hidden', 'true')
      const label = document.createElement('span')
      label.className = 'intake-ai-btn__label'
      label.textContent = defaultLabel
      btn.append(spin, label)
    }

    systemEl?.addEventListener('input', () => showAiAssistHint(''))
    const unlockAndMatch = () => {
      companyMatchUnlocked = true
      tryStartCompanyMatch()
    }
    systemEl?.addEventListener('focus', unlockAndMatch)
    systemEl?.addEventListener('mousedown', unlockAndMatch)

    companyEl?.addEventListener('input', () => {
      showAiAssistHint('')
      const q = (companyEl.value || '').trim()
      if (q !== companyMatchQuerySynced) {
        if (companyMatchTimer) window.clearTimeout(companyMatchTimer)
        companyMatchCache = null
        companyMatchQuerySynced = ''
        companyResolvedName = ''
        setCompanyMatchResult('hidden')
        const listEl = document.getElementById('intake-ai-company-suggest')
        if (listEl) {
          listEl.hidden = true
          listEl.innerHTML = ''
        }
        companyEl.setAttribute('aria-expanded', 'false')
        if (!companyMatchUnlocked) {
          if (q.length >= 2) {
            setCompanyMatchHint('点选「系统 / 业务类型」开始匹配公司')
          } else {
            setCompanyMatchHint('')
          }
        } else if (q.length >= 2) {
          scheduleCompanyMatch()
        } else {
          setCompanyMatchHint('')
        }
      }
    })
    companyEl?.addEventListener('blur', (ev) => {
      const q = (companyEl.value || '').trim()
      const next = ev.relatedTarget
      const towardSystem =
        next === systemEl || (systemEl && typeof systemEl.contains === 'function' && systemEl.contains(next))
      if (companyMatchUnlocked) return
      if (q.length >= 2 && q !== companyMatchQuerySynced && !towardSystem) {
        setCompanyMatchResult('hidden')
        setCompanyMatchHint('点选「系统 / 业务类型」开始匹配公司')
      }
      window.setTimeout(() => {
        const listEl = document.getElementById('intake-ai-company-suggest')
        if (listEl) listEl.hidden = true
        companyEl?.setAttribute('aria-expanded', 'false')
      }, 160)
    })
    document.addEventListener('click', (ev) => {
      const wrap = document.querySelector('.intake-company-wrap')
      if (wrap && !wrap.contains(ev.target)) {
        const listEl = document.getElementById('intake-ai-company-suggest')
        if (listEl) listEl.hidden = true
        companyEl?.setAttribute('aria-expanded', 'false')
      }
    })

    btn?.addEventListener('click', async () => {
      const typedCompany = (companyEl?.value || '').trim()
      const system = (systemEl?.value || '').trim()
      if (!typedCompany || !system) {
        showAiAssistHint('请填写公司名称和系统 / 业务类型')
        ;(typedCompany ? systemEl : companyEl)?.focus()
        return
      }
      await executeAiAssistFill(typedCompany, system)
    })
  }

  let validationHintEl = null

  function showValidationHint(msg) {
    if (!btnNext) return
    if (!validationHintEl) {
      validationHintEl = document.createElement('p')
      validationHintEl.id = 'intake-validation-hint'
      validationHintEl.className = 'intake-validation-hint'
      validationHintEl.setAttribute('role', 'alert')
      btnNext.parentElement?.insertBefore(validationHintEl, btnNext)
    }
    validationHintEl.textContent = msg
    validationHintEl.hidden = false
  }

  function clearValidationHint() {
    if (validationHintEl) validationHintEl.hidden = true
  }

  function focusFirstError(fallbackMsg) {
    const panel = form.querySelector('.intake-step-panel.is-active')
    if (!panel) return
    const errors = Array.from(panel.querySelectorAll('.form-error')).filter((el) => (el.textContent || '').trim())
    const errText = errors.map((el) => el.textContent.trim()).filter(Boolean)
    if (fallbackMsg || errText.length) {
      showValidationHint(errText[0] || fallbackMsg)
    }
    const fieldId = errors[0]?.id?.replace(/-error$/, '')
    const field =
      (fieldId && panel.querySelector(`#${fieldId}`)) ||
      panel.querySelector('textarea:invalid, input:invalid, select:invalid') ||
      panel.querySelector('textarea, input[type="text"], input[type="email"]')
    panel.classList.add('intake-panel--error')
    window.setTimeout(() => panel.classList.remove('intake-panel--error'), 2400)
    if (field?.focus) {
      scrollFieldIntoWizard(field)
      field.focus()
    } else {
      scrollIntakeWizardToTop()
    }
  }

  const INTAKE_SCROLL_OFFSET = 88

  function scrollIntakeWizardToTop() {
    const target =
      form.querySelector('.intake-progress') || form.querySelector('.intake-step-panel.is-active')
    if (!target) return
    const top = target.getBoundingClientRect().top + window.scrollY - INTAKE_SCROLL_OFFSET
    window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
  }

  function scrollFieldIntoWizard(field) {
    if (!field) return
    const top = field.getBoundingClientRect().top + window.scrollY - INTAKE_SCROLL_OFFSET - 12
    window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
  }

  function goStep(delta) {
    const step = STEPS[stepIndex]
    if (delta > 0) {
      const validate = validators[step.id]
      if (validate && !validate()) {
        focusFirstError()
        return
      }
    }
    clearValidationHint()
    stepIndex = Math.max(0, Math.min(STEPS.length - 1, stepIndex + delta))
    updateUi()
    scrollIntakeWizardToTop()
  }

  btnPrev?.addEventListener('click', () => goStep(-1))
  btnNext?.addEventListener('click', () => goStep(1))

  stepNodes.forEach((node, idx) => {
    node.addEventListener('click', () => {
      if (idx < stepIndex) {
        stepIndex = idx
        updateUi()
        scrollIntakeWizardToTop()
      }
    })
  })

  form.addEventListener('input', updateChecklist)
  form.addEventListener('change', updateChecklist)

  form.addEventListener('submit', async (event) => {
    event.preventDefault()
    if (stepIndex !== STEPS.length - 1) {
      goStep(1)
      return
    }
    if (apiError) apiError.textContent = ''
    if (success) success.classList.remove('visible')

    const order = ['profile', 'problem', 'workflow', 'contact', 'plan']
    for (const id of order) {
      if (!validators[id]()) {
        stepIndex = STEPS.findIndex((s) => s.id === id)
        updateUi()
        return
      }
    }

    if (btnSubmit) btnSubmit.disabled = true
    try {
      const csrf = readCookie('csrf_token')
      if (!csrf) {
        if (apiError) {
          apiError.textContent = '页面会话已过期，请刷新后重试。'
        }
        return
      }

      const payload = {
        name: state.name,
        email: state.email,
        phone: state.phone,
        company: state.company,
        message: buildMessage(),
        source: csIntake.active ? 'cs_intake' : 'contact',
      }
      if (csIntake.active && csIntake.uid && csIntake.token) {
        payload.cs_uid = csIntake.uid
        payload.cs_t = csIntake.token
      }

      const res = await fetch('/api/public/contact', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': csrf,
        },
        body: JSON.stringify(payload),
      })

      if (res.ok) {
        let auditCode = ''
        try {
          const data = await res.json()
          auditCode = auditCodeFromSubmitResponse(data)
        } catch {
          /* ignore */
        }
        showContactSubmitSuccess(auditCode)
        form.querySelector('.intake-wizard-body')?.classList.add('is-submitted')
        form.querySelector('.intake-wizard-actions')?.setAttribute('hidden', '')
        syncAiAssistUi()
        window.scrollTo({ top: success?.offsetTop ? success.offsetTop - 80 : 0, behavior: 'smooth' })
        return
      }

      let msg = '提交失败，请稍后重试。'
      if (res.status === 429) msg = '提交过于频繁，请稍后再试。'
      else if (res.status === 403) msg = '请刷新页面后重试。'
      try {
        const data = await res.json()
        if (data?.detail && typeof data.detail === 'string') msg = data.detail
      } catch {
        /* ignore */
      }
      if (apiError) apiError.textContent = msg
    } catch {
      if (apiError) apiError.textContent = '网络错误，请检查连接后重试。'
    } finally {
      if (btnSubmit) btnSubmit.disabled = false
    }
  })

  function goToStepById(stepId) {
    const idx = STEPS.findIndex((s) => s.id === stepId)
    if (idx < 0) return false
    stepIndex = idx
    clearValidationHint()
    updateUi()
    scrollIntakeWizardToTop()
    return true
  }

  function applyDraft(partial) {
    if (!partial || typeof partial !== 'object') return
    const allowed = Object.keys(state)
    for (const key of allowed) {
      if (!(key in partial)) continue
      const val = partial[key]
      if (key === 'directions') {
        state.directions = Array.isArray(val) ? val.map(String) : []
      } else if (typeof val === 'string' || typeof val === 'number') {
        state[key] = String(val).trim()
      }
    }
    syncFieldsFromState()
    updateChecklist()
    updateUi()
  }

  function highlightField(fieldId) {
    const el = document.getElementById(fieldId)
    if (!el) return
    scrollFieldIntoWizard(el)
    el.classList.add('intake-field--highlight')
    window.setTimeout(() => el.classList.remove('intake-field--highlight'), 2200)
    if (typeof el.focus === 'function') el.focus()
  }

  function validateCurrentStep() {
    const step = STEPS[stepIndex]
    const fn = validators[step.id]
    return fn ? fn() : true
  }

  function isSubmitted() {
    return Boolean(form.querySelector('.intake-wizard-body')?.classList.contains('is-submitted'))
  }

  const csrfOk = await ensureCsrfCookie()
  if (!csrfOk && apiError) {
    apiError.textContent = '会话初始化未完成，提交前请刷新页面（Cmd+Shift+R）。'
  }

  applyCsIntakeFromUrl()
  initAiAssistEntry()
  updateUi()
  form.dataset.intakeReady = 'true'

  window.XcContactIntake = {
    getState: () => ({ ...state, directions: [...state.directions] }),
    goToStep: goToStepById,
    applyDraft,
    highlightField,
    validateCurrentStep,
    buildMessage,
    isSubmitted,
    getCurrentStepId: () => STEPS[stepIndex]?.id || 'profile',
    stepIds: () => STEPS.map((s) => s.id),
    runAiAssistFill: ({ company, system }) => executeAiAssistFill(company, system),
    selectAiCompany: (item) => selectCompanyFromMatch(item, { exact: true }),
  }
})
