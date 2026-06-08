import { ref } from 'vue'

export interface DangerConfirmOptions {
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  destructive?: boolean
}

const open = ref(false)
const options = ref<DangerConfirmOptions | null>(null)
let resolver: ((ok: boolean) => void) | null = null

export function confirmDanger(opts: DangerConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    resolver = resolve
    options.value = opts
    open.value = true
  })
}

export function resolveDangerConfirm(ok: boolean) {
  open.value = false
  const r = resolver
  resolver = null
  options.value = null
  r?.(ok)
}

export function useDangerConfirmState() {
  return { open, options }
}
