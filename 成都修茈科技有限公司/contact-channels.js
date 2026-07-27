/** 联系我们页 · 底部渠道入口（先企微，后续可扩微信/电话等） */
;(function () {
  function bootContactChannels() {
    if (window.__contactChannelsReady) return
    window.__contactChannelsReady = true

    const root = document.querySelector('.contact-channels')
    if (!root) return

    const buttons = Array.from(root.querySelectorAll('.contact-channel-btn[data-channel]'))
    const panels = Array.from(root.querySelectorAll('[data-channel-panel]'))

    function closeAll() {
      buttons.forEach((btn) => {
        btn.classList.remove('is-open')
        btn.setAttribute('aria-expanded', 'false')
      })
      panels.forEach((panel) => {
        panel.hidden = true
      })
    }

    function openChannel(channel) {
      const btn = buttons.find((item) => item.dataset.channel === channel)
      const panel = panels.find((item) => item.dataset.channelPanel === channel)
      if (!btn || !panel) return
      const alreadyOpen = btn.getAttribute('aria-expanded') === 'true'
      closeAll()
      if (alreadyOpen) return
      btn.classList.add('is-open')
      btn.setAttribute('aria-expanded', 'true')
      panel.hidden = false
      panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }

    buttons.forEach((btn) => {
      btn.addEventListener('click', () => {
        openChannel(String(btn.dataset.channel || ''))
      })
    })

    root.querySelectorAll('[data-copy-target]').forEach((copyBtn) => {
      copyBtn.addEventListener('click', async () => {
        const targetId = String(copyBtn.getAttribute('data-copy-target') || '')
        const target = targetId ? document.getElementById(targetId) : null
        const text = (target?.textContent || '').trim()
        const status = document.getElementById('contact-wecom-copy-status')
        if (!text) return
        try {
          if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(text)
          } else {
            const ta = document.createElement('textarea')
            ta.value = text
            ta.setAttribute('readonly', '')
            ta.style.position = 'fixed'
            ta.style.left = '-9999px'
            document.body.appendChild(ta)
            ta.select()
            document.execCommand('copy')
            document.body.removeChild(ta)
          }
          if (status) status.textContent = '已复制企微客服链接'
          window.setTimeout(() => {
            if (status) status.textContent = ''
          }, 2200)
        } catch {
          if (status) status.textContent = '复制失败，请手动选择链接'
        }
      })
    })

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeAll()
    })
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootContactChannels)
  } else {
    bootContactChannels()
  }
})()
