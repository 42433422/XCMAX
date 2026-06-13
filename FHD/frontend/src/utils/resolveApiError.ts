import type { Composer } from 'vue-i18n'

type ErrorPayload = {
  code?: string
  message?: string
}

type TranslateFn = Composer['t'] | ((key: string) => string)

/** Map API ``error.code`` to i18n string; fallback to server message. */
export function resolveApiErrorMessage(
  t: TranslateFn,
  payload: ErrorPayload | null | undefined,
  fallback = '',
): string {
  const code = payload?.code
  if (code) {
    const key = `errors.${code}`
    const translated = t(key)
    if (translated !== key) return String(translated)
  }
  return String(payload?.message || fallback)
}
