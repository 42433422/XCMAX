/**
 * Inject shared header/footer into pages that mount empty #site-header / #site-footer.
 * Homepage (index.html) depends on this. Missing partials previously fell through to
 * index.html, so the nav never appeared.
 */
;(function () {
  'use strict'

  var PAGE =
    (document.body && document.body.getAttribute('data-page')) ||
    (location.pathname || '').replace(/^\//, '').replace(/\.html$/, '') ||
    'index'

  function markActive(root) {
    if (!root) return
    root.querySelectorAll('[data-nav]').forEach(function (el) {
      if (el.getAttribute('data-nav') === PAGE) {
        el.classList.add('active')
      }
    })
  }

  function inject(selector, html) {
    var mount = document.querySelector(selector)
    if (!mount || !html) return
    mount.outerHTML = html.trim()
  }

  function bindMobileMenu() {
    var toggle = document.getElementById('mobile-menu-toggle')
    var menu = document.getElementById('mobile-menu')
    var overlay = document.getElementById('mobile-menu-overlay')
    if (!toggle || !menu || !overlay || toggle.dataset.bound === '1') return
    toggle.dataset.bound = '1'

    function closeMenu() {
      menu.classList.remove('active')
      overlay.classList.remove('active')
      toggle.classList.remove('active')
      toggle.setAttribute('aria-expanded', 'false')
      toggle.setAttribute('aria-label', '打开菜单')
      document.body.classList.remove('nav-open')
    }

    toggle.addEventListener('click', function () {
      var open = menu.classList.toggle('active')
      overlay.classList.toggle('active', open)
      toggle.classList.toggle('active', open)
      toggle.setAttribute('aria-expanded', String(open))
      toggle.setAttribute('aria-label', open ? '关闭菜单' : '打开菜单')
      document.body.classList.toggle('nav-open', open)
    })
    overlay.addEventListener('click', closeMenu)
    menu.querySelectorAll('.mobile-menu-link').forEach(function (link) {
      link.addEventListener('click', closeMenu)
    })
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') closeMenu()
    })
  }

  function bindBackToTop() {
    var backToTop = document.getElementById('back-to-top')
    if (!backToTop || backToTop.dataset.bound === '1') return
    backToTop.dataset.bound = '1'
    var update = function () {
      backToTop.classList.toggle('visible', window.scrollY > 420)
    }
    update()
    window.addEventListener('scroll', update, { passive: true })
    backToTop.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' })
    })
  }

  function loadPartial(url) {
    return fetch(url, { credentials: 'same-origin', cache: 'no-cache' }).then(function (res) {
      if (!res.ok) {
        throw new Error('partial ' + url + ' -> ' + res.status)
      }
      return res.text().then(function (text) {
        if (/<!DOCTYPE html>/i.test(text) || /<html[\s>]/i.test(text)) {
          throw new Error('partial ' + url + ' returned a full HTML document fallback')
        }
        return text
      })
    })
  }

  function boot() {
    var jobs = []
    if (document.getElementById('site-header')) {
      jobs.push(
        loadPartial('/partials/header.html').then(function (html) {
          inject('#site-header', html)
          markActive(document)
          bindMobileMenu()
        }),
      )
    }
    if (document.getElementById('site-footer')) {
      jobs.push(
        loadPartial('/partials/footer.html').then(function (html) {
          inject('#site-footer', html)
          var year = document.getElementById('year')
          if (year) year.textContent = String(new Date().getFullYear())
          bindBackToTop()
        }),
      )
    }
    return Promise.all(jobs)
      .then(function () {
        document.dispatchEvent(new CustomEvent('xcagi:site-chrome-ready'))
      })
      .catch(function (err) {
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('[site-partials]', err)
        }
      })
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot)
  } else {
    boot()
  }
})()
