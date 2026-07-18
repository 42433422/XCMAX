/**
 * partials-loader.js — 注入 header/footer 片段，初始化导航状态与移动菜单。
 * 每个页面在 <body> 开头放 <div id="site-header"></div>，结尾放 <div id="site-footer"></div>，
 * 然后在 main.js 之前引入本脚本。
 */
;(function () {
  const headerSlot = document.getElementById('site-header')
  const footerSlot = document.getElementById('site-footer')
  if (!headerSlot && !footerSlot) return

  const page = (document.body.dataset.page || '').trim()

  function inject(slot, url, cb) {
    fetch(url)
      .then((r) => (r.ok ? r.text() : Promise.reject(r.status)))
      .then((html) => {
        slot.outerHTML = html
        if (cb) cb()
      })
      .catch(() => {})
  }

  function markActive() {
    if (!page) return
    const links = document.querySelectorAll('.nav-menu a[data-nav]')
    links.forEach((a) => {
      if (a.dataset.nav === page) a.classList.add('active')
    })
  }

  function initMobileMenu() {
    const toggle = document.getElementById('mobile-menu-toggle')
    const menu = document.getElementById('mobile-menu')
    const overlay = document.getElementById('mobile-menu-overlay')
    if (!toggle || !menu || !overlay) return

    function close() {
      menu.classList.remove('active')
      overlay.classList.remove('active')
      toggle.classList.remove('active')
      toggle.setAttribute('aria-expanded', 'false')
      toggle.setAttribute('aria-label', '打开菜单')
      document.body.classList.remove('nav-open')
    }

    toggle.addEventListener('click', () => {
      const open = menu.classList.toggle('active')
      overlay.classList.toggle('active', open)
      toggle.classList.toggle('active', open)
      toggle.setAttribute('aria-expanded', String(open))
      toggle.setAttribute('aria-label', open ? '关闭菜单' : '打开菜单')
      document.body.classList.toggle('nav-open', open)
    })
    overlay.addEventListener('click', close)
    menu.querySelectorAll('.mobile-menu-link').forEach((l) => l.addEventListener('click', close))
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') close()
    })
  }

  function initYear() {
    const y = document.getElementById('year')
    if (y) y.textContent = String(new Date().getFullYear())
  }

  function initBackToTop() {
    const btn = document.getElementById('back-to-top')
    if (!btn) return
    const update = () => btn.classList.toggle('visible', window.scrollY > 420)
    update()
    window.addEventListener('scroll', update, { passive: true })
    btn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }))
  }

  let pending = 0
  function done() {
    if (--pending <= 0) {
      markActive()
      initMobileMenu()
      initYear()
      initBackToTop()
      // 通知 main.js 片段已就绪
      document.dispatchEvent(new CustomEvent('partials:ready'))
    }
  }

  if (headerSlot) { pending++; inject(headerSlot, '/partials/header.html', done) }
  if (footerSlot) { pending++; inject(footerSlot, '/partials/footer.html', done) }
})()
