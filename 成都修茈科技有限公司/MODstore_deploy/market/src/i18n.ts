import { inject, reactive, type App } from 'vue'
import zhCN from './locales/zh-CN'
import enUS from './locales/en-US'

export const I18N_KEY = Symbol('modstore-i18n')

type Locale = 'zh-CN' | 'en-US'
type LocaleMessages = Record<string, unknown>

const messages: Record<Locale, LocaleMessages> = {
  'zh-CN': zhCN as LocaleMessages,
  'en-US': enUS as LocaleMessages,
}

function readPath(source: unknown, path: string): unknown {
  return String(path)
    .split('.')
    .reduce<unknown>((cur, key) => {
      if (cur && typeof cur === 'object' && Object.prototype.hasOwnProperty.call(cur, key)) {
        return (cur as Record<string, unknown>)[key]
      }
      return undefined
    }, source)
}

function storedLocale(): Locale {
  try {
    const raw = localStorage.getItem('modstore_locale')
    if (raw === 'en-US' || raw === 'zh-CN') return raw
    return 'zh-CN'
  } catch {
    return 'zh-CN'
  }
}

export function createModstoreI18n(defaultLocale: Locale = storedLocale()) {
  const state = reactive({
    locale: (messages[defaultLocale] ? defaultLocale : 'zh-CN') as Locale,
  })

  function setLocale(locale: Locale) {
    if (!messages[locale]) return
    state.locale = locale
    try {
      localStorage.setItem('modstore_locale', locale)
    } catch {
      /* ignore storage errors */
    }
  }

  function t(path: string, params: Record<string, string | number> = {}): string {
    const value = readPath(messages[state.locale], path) ?? readPath(messages['zh-CN'], path) ?? path
    return String(value).replace(/\{(\w+)\}/g, (_, key: string) =>
      params[key] === undefined ? `{${key}}` : String(params[key]),
    )
  }

  return {
    install(app: App) {
      app.provide(I18N_KEY, { state, t, setLocale, messages })
      app.config.globalProperties.$t = t
    },
    state,
    t,
    setLocale,
    messages,
  }
}

export function useI18n() {
  return inject(I18N_KEY, createModstoreI18n()) as ReturnType<typeof createModstoreI18n>
}
