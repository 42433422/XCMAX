import { createI18n } from 'vue-i18n'
import zhCN from './locales/zh-CN'
import enUS from './locales/en-US'

const LOCALE_KEY = 'xcagi_locale'

function detectLocale(): string {
  if (typeof window === 'undefined') return 'zh-CN'
  try {
    const stored = window.localStorage.getItem(LOCALE_KEY)
    if (stored === 'en-US' || stored === 'zh-CN') return stored
  } catch {
    /* ignore */
  }
  // 词条覆盖尚不完整：默认统一 zh-CN，避免浏览器语言为英文时出现中英混排；
  // 用户在设置中显式切换后（localStorage 有值）才使用 en-US。
  return 'zh-CN'
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
