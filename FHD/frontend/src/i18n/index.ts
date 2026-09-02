import { createI18n } from 'vue-i18n'
import { enUSMessages, zhCNMessages } from './locales/messages'

const LOCALE_KEY = 'xcagi_locale'

export function detectLocale(): 'zh-CN' | 'en-US' {
  if (typeof window === 'undefined') return 'zh-CN'
  const stored = window.localStorage.getItem(LOCALE_KEY)
  if (stored === 'en-US' || stored === 'zh-CN') return stored
  // XCAGI 桌面端以中文业务模块为主。不要仅因操作系统是英文就把通用控件
  // 自动切成英文，否则会出现中文业务内容 + 英文按钮的割裂体验。
  // 用户仍可在设置中显式切换并持久化英文。
  return 'zh-CN'
}

export const i18n = createI18n({
  legacy: false,
  locale: detectLocale(),
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCNMessages,
    'en-US': enUSMessages,
  },
})

export function setAppLocale(locale: 'zh-CN' | 'en-US') {
  i18n.global.locale.value = locale
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(LOCALE_KEY, locale)
  }
}

export default i18n
