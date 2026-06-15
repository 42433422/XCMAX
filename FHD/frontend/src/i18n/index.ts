import { createI18n } from 'vue-i18n'
import zhCN from './locales/zh-CN'
import enUS from './locales/en-US'

const LOCALE_KEY = 'xcagi_locale'

function detectLocale(): string {
  if (typeof window === 'undefined') return 'zh-CN'
  const stored = window.localStorage.getItem(LOCALE_KEY)
  if (stored === 'en-US' || stored === 'zh-CN') return stored
  const nav = navigator.language || ''
  return nav.toLowerCase().startsWith('en') ? 'en-US' : 'zh-CN'
}

export const i18n = createI18n({
  legacy: false,
  locale: detectLocale(),
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
})

export function setAppLocale(locale: 'zh-CN' | 'en-US') {
  i18n.global.locale.value = locale
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(LOCALE_KEY, locale)
  }
}

export default i18n
