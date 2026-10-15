document.addEventListener('DOMContentLoaded', async () => {
  const form = document.getElementById('quick-contact-form')
  if (!form) return
  const error = document.getElementById('quick-contact-error'), success = document.getElementById('quick-contact-success')
  const submit = form.querySelector('button[type="submit"]')
  const cookie = (name) => document.cookie.split('; ').find((part) => part.startsWith(`${name}=`))?.slice(name.length + 1) || ''
  try { await fetch('/api/health', { credentials: 'same-origin' }) } catch { /* submit reports connectivity */ }
  form.addEventListener('submit', async (event) => {
    event.preventDefault(); error.textContent = ''
    const csrf = cookie('csrf_token')
    if (!csrf) { error.textContent = '页面会话尚未建立，请刷新后重试。'; return }
    const values = new FormData(form); submit.disabled = true
    try {
      const response = await fetch('/api/public/contact', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify({ name: String(values.get('name') || '').trim(), email: String(values.get('email') || '').trim(), message: String(values.get('message') || '').trim(), source: 'contact_quick', privacy_agreed: true, privacy_version: '2026-06-20', privacy_url: '/privacy.html' }) })
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || '提交失败，请稍后重试。') }
      form.hidden = true; success.hidden = false
    } catch (cause) { error.textContent = cause instanceof Error ? cause.message : '网络错误，请检查连接后重试。'; submit.disabled = false }
  })
})
