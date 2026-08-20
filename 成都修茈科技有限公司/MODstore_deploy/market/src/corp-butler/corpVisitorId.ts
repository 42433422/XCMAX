/** 官网未登录访客稳定 ID（小C 对话对象）。 */

const STORAGE_KEY = 'xc_corp_visitor_id'
const LABEL_KEY = 'xc_corp_visitor_label'

function randomVisitorId(): string {
  const raw =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID().replace(/-/g, '')
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`
  return `v_${raw.slice(0, 32)}`
}

export function getOrCreateCorpVisitorId(): string {
  try {
    const existing = String(localStorage.getItem(STORAGE_KEY) || '').trim()
    if (/^v_[A-Za-z0-9_-]{8,64}$/.test(existing)) return existing
    const next = randomVisitorId()
    localStorage.setItem(STORAGE_KEY, next)
    return next
  } catch {
    return randomVisitorId()
  }
}

export function getCorpVisitorLabel(): string {
  try {
    return String(localStorage.getItem(LABEL_KEY) || '')
      .trim()
      .slice(0, 32)
  } catch {
    return ''
  }
}

export function setCorpVisitorLabel(label: string): void {
  const v = String(label || '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 32)
  try {
    if (v) localStorage.setItem(LABEL_KEY, v)
    else localStorage.removeItem(LABEL_KEY)
  } catch {
    // ignore
  }
}
