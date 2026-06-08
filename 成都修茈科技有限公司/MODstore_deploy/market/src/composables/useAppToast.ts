import { ref } from 'vue'

export type AppToastVariant = 'info' | 'success' | 'error'

export interface AppToastItem {
  id: number
  message: string
  variant: AppToastVariant
}

const toasts = ref<AppToastItem[]>([])
let nextId = 1

export function showAppToast(message: string, opts?: { variant?: AppToastVariant; durationMs?: number }) {
  const id = nextId++
  const variant = opts?.variant ?? 'info'
  const durationMs = opts?.durationMs ?? (variant === 'error' ? 6000 : 4000)
  toasts.value = [...toasts.value, { id, message: String(message || '').trim(), variant }]
  if (durationMs > 0) {
    window.setTimeout(() => dismissAppToast(id), durationMs)
  }
  return id
}

export function dismissAppToast(id: number) {
  toasts.value = toasts.value.filter((t) => t.id !== id)
}

export function useAppToastState() {
  return { toasts }
}
