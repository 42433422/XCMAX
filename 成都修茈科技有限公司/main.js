document.addEventListener('DOMContentLoaded', () => {
  const year = document.getElementById('year')
  if (year) year.textContent = String(new Date().getFullYear())

  const toggle = document.getElementById('mobile-menu-toggle')
  const menu = document.getElementById('mobile-menu')
  const overlay = document.getElementById('mobile-menu-overlay')
  const links = document.querySelectorAll('.mobile-menu-link')

  function closeMenu() {
    if (!toggle || !menu || !overlay) return
    menu.classList.remove('active')
    overlay.classList.remove('active')
    toggle.classList.remove('active')
    toggle.setAttribute('aria-expanded', 'false')
    toggle.setAttribute('aria-label', '打开菜单')
    document.body.classList.remove('nav-open')
  }

  if (toggle && menu && overlay) {
    toggle.addEventListener('click', () => {
      const open = menu.classList.toggle('active')
      overlay.classList.toggle('active', open)
      toggle.classList.toggle('active', open)
      toggle.setAttribute('aria-expanded', String(open))
      toggle.setAttribute('aria-label', open ? '关闭菜单' : '打开菜单')
      document.body.classList.toggle('nav-open', open)
    })
    overlay.addEventListener('click', closeMenu)
    links.forEach((link) => link.addEventListener('click', closeMenu))
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeMenu()
    })
  }

  const revealItems = document.querySelectorAll('.reveal')
  if ('IntersectionObserver' in window && revealItems.length) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return
          const delay = Number(entry.target.dataset.delay || 0)
          window.setTimeout(() => entry.target.classList.add('visible'), delay)
          observer.unobserve(entry.target)
        })
      },
      { threshold: 0.12, rootMargin: '0px 0px -40px 0px' },
    )
    revealItems.forEach((item) => observer.observe(item))
  } else {
    revealItems.forEach((item) => item.classList.add('visible'))
  }

  const backToTop = document.getElementById('back-to-top')
  if (backToTop) {
    const update = () => backToTop.classList.toggle('visible', window.scrollY > 420)
    update()
    window.addEventListener('scroll', update, { passive: true })
    backToTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }))
  }

  const form = document.getElementById('contact-form')
  const success = document.getElementById('form-success')
  if (form && form.dataset.intakeWizard === 'true') {
    /* 多步骤需求采集由 contact-intake.js 处理 */
  } else if (form) {
    const apiError = document.getElementById('form-api-error')
    const submitBtn = document.getElementById('submit-btn')

    const rules = {
      name: (value) => {
        const t = value.trim()
        if (!t) return '请输入姓名'
        if (t.length > 128) return '姓名不能超过 128 个字符'
        return ''
      },
      phone: (value) =>
        value.trim() && !/^1[3-9]\d{9}$/.test(value.trim()) ? '请输入有效的手机号码' : '',
      email: (value) => {
        const t = value.trim()
        if (!t) return '请输入邮箱'
        if (t.length > 256) return '邮箱过长'
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(t) ? '' : '请输入有效的邮箱地址'
      },
      company: (value) => (value.trim().length > 256 ? '公司名称不能超过 256 个字符' : ''),
      message: (value) => {
        const t = value.trim()
        if (!t) return '请输入需求描述'
        if (t.length < 10) return '需求描述至少需要 10 个字符'
        if (t.length > 8000) return '需求描述不能超过 8000 个字符'
        return ''
      },
    }

    function readCookie(name) {
      const parts = (`; ${document.cookie}`).split(`; ${name}=`)
      if (parts.length === 2) return parts.pop().split(';').shift() || ''
      return ''
    }

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

    function formatApiDetail(data) {
      if (!data || data.detail == null) return ''
      const d = data.detail
      if (typeof d === 'string') return d
      if (Array.isArray(d)) {
        return d
          .map((x) => (x && typeof x === 'object' && x.msg ? x.msg : String(x)))
          .join('；')
      }
      return String(d)
    }

    function validateField(name) {
      const input = form.elements[name]
      const errorNode = document.getElementById(`${name}-error`)
      if (!input || !rules[name]) return true
      const message = rules[name](input.value || '')
      if (errorNode) errorNode.textContent = message
      return !message
    }

    Object.keys(rules).forEach((name) => {
      const input = form.elements[name]
      if (!input) return
      input.addEventListener('blur', () => validateField(name))
      input.addEventListener('input', () => validateField(name))
    })

    fetch('/api/health', { credentials: 'same-origin' }).catch(() => {})

    form.addEventListener('submit', async (event) => {
      event.preventDefault()
      if (apiError) apiError.textContent = ''
      if (success) success.classList.remove('visible')

      const ok = Object.keys(rules).every(validateField)
      if (!ok) return

      if (submitBtn) submitBtn.disabled = true
      try {
        await fetch('/api/health', { credentials: 'same-origin', method: 'GET' })

        const csrf = readCookie('csrf_token')
        if (!csrf) {
          if (apiError) {
            apiError.textContent =
              '无法获取安全令牌（请确认已启用 ModStore 且使用同源访问），请刷新页面后重试。'
          }
          return
        }

        const payload = {
          name: form.elements.name.value.trim(),
          email: form.elements.email.value.trim(),
          phone: (form.elements.phone.value || '').trim(),
          company: (form.elements.company.value || '').trim(),
          message: form.elements.message.value.trim(),
          source: 'contact',
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
          if (success) {
            success.removeAttribute('hidden')
            if (auditCode) {
              success.textContent = `提交成功。您的需求审核码为 ${auditCode}，请保存以便查询进度。`
            } else {
              success.textContent =
                '提交成功。我们已收到您的需求；若未显示审核码，请刷新后重试或联系客服。'
            }
            success.classList.add('visible')
          }
          form.reset()
          return
        }

        let msg = '提交失败，请稍后重试。'
        if (res.status === 429) msg = '提交过于频繁，请稍后再试。'
        else if (res.status === 403) msg = '安全校验失败，请刷新页面后重试。'
        else if (res.status === 502) msg = '服务暂时不可用，请稍后重试。'
        try {
          const data = await res.json()
          const d = formatApiDetail(data)
          if (d) msg = d
        } catch {
          /* ignore */
        }
        if (apiError) apiError.textContent = msg
      } catch {
        if (apiError) apiError.textContent = '网络错误，请检查连接后重试。'
      } finally {
        if (submitBtn) submitBtn.disabled = false
      }
    })
  }

})

/** 官网 AI 管家（/market/ 内由 Vue 应用自带） */
function bootCorpButler() {
  if (/^\/market(\/|$)/.test(window.location.pathname)) return
  loadCorpButler()
}

function loadCorpButler() {
  let root = document.getElementById('xc-corp-butler-root')
  if (!root) {
    root = document.createElement('div')
    root.id = 'xc-corp-butler-root'
    document.body.appendChild(root)
  }
  const ver = '20260616'
  if (!document.querySelector('link[data-xc-corp-butler-css]')) {
    const css = document.createElement('link')
    css.rel = 'stylesheet'
    css.href = `/corp-butler/corp-butler.css?v=${ver}`
    css.setAttribute('data-xc-corp-butler-css', '1')
    document.head.appendChild(css)
  }
  if (!document.querySelector('script[data-xc-corp-butler-js]')) {
    const script = document.createElement('script')
    script.type = 'module'
    script.src = `/corp-butler/corp-butler.js?v=${ver}`
    script.setAttribute('data-xc-corp-butler-js', '1')
    script.addEventListener('error', () => {
      console.warn('[xc-corp-butler] 脚本加载失败，请强制刷新页面')
    })
    document.body.appendChild(script)
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootCorpButler)
} else {
  bootCorpButler()
}
