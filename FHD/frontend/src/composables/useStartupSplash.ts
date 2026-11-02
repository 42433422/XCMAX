import { inject, onActivated, onBeforeUnmount, onDeactivated, ref, type InjectionKey } from 'vue'
import { captureAuthSession } from '@/utils/authSessionCache'

export const STARTUP_READY_TIMEOUT_MS = 20_000

type PreparePage = (signal: AbortSignal) => Promise<void>
export const startupPageReadyKey: InjectionKey<(prepare: PreparePage) => () => void> = Symbol('startup-page-ready')

/** The mounted page owns its necessary data; the shell awaits the same read and retries it explicitly. */
export function useStartupPageReady(load: (current: () => boolean) => Promise<void>, scopeKey: () => unknown = () => undefined) {
  let version = 0, disposed = false, active = true, claimed = false
  let pending: Promise<void> | undefined
  let ownerCurrent = () => false
  function begin() {
    const request = ++version, sessionCurrent = captureAuthSession(), key = scopeKey()
    const current = () => !disposed && active && request === version && sessionCurrent() && Object.is(key, scopeKey())
    ownerCurrent = current
    pending = Promise.resolve().then(async () => {
      if (!current()) throw new Error('当前页面已改变，请重试')
      await load(current)
      if (!current()) throw new Error('当前页面已改变，请重试')
    })
    // The page also runs during ordinary navigation, outside a startup attempt.
    void pending.catch(() => {})
    return pending
  }
  const register = inject(startupPageReadyKey, null)
  const prepare: PreparePage = async signal => {
    if (!pending || claimed || !ownerCurrent()) begin()
    claimed = true
    const request = version
    const retire = () => { if (request === version) version++ }
    signal.addEventListener('abort', retire, { once: true })
    if (signal.aborted) retire()
    try { await pending } finally { signal.removeEventListener('abort', retire) }
  }
  let unregister = register?.(prepare)
  onActivated(() => { active = true; unregister ??= register?.(prepare) })
  onDeactivated(() => { active = false; version++; unregister?.(); unregister = undefined })
  onBeforeUnmount(() => { disposed = true; version++; unregister?.() })
  return () => { claimed = false; return begin() }
}

/** Only the local icon face is critical; unrelated fonts and business assets stay in the background. */
export async function waitForCriticalFonts(): Promise<void> {
  if (!document.fonts?.load) return
  const faces = await document.fonts.load('14px FontAwesome', '\uf015')
  if (!faces.length || faces.some(face => face.status !== 'loaded')) {
    throw new Error('工作台图标未加载完成，请重试或重新加载')
  }
}

/** A deadline exposes recovery; it must never count as readiness. */
export function useStartupSplash() {
  const startupVisible = ref(true)
  const appReady = ref(false)
  const startupError = ref('')
  const startupStage = ref('正在准备工作台…')
  let generation = 0
  let deadline: ReturnType<typeof setTimeout> | undefined
  let disposed = false
  let attempt: AbortController | undefined

  function retire() {
    generation++
    attempt?.abort()
    clearTimeout(deadline)
    deadline = undefined
  }

  async function runStartup(task: (current: () => boolean, stage: (text: string) => void, signal: AbortSignal) => Promise<void>) {
    retire()
    attempt = new AbortController()
    const request = generation
    const current = () => !disposed && request === generation
    startupVisible.value = true
    appReady.value = false
    startupError.value = ''
    startupStage.value = '正在准备工作台…'
    try {
      await Promise.race([
        task(current, text => { if (current()) startupStage.value = text }, attempt.signal),
        new Promise<never>((_, reject) => {
          deadline = setTimeout(() => reject(new Error('准备工作台超时，请重试或重新加载')), STARTUP_READY_TIMEOUT_MS)
        }),
      ])
      if (!current()) return
      // Keep this successful session current for optional background handoff.
      // The next attempt, account change, cancellation or teardown retires it.
      clearTimeout(deadline)
      deadline = undefined
      startupVisible.value = false
      appReady.value = true
    } catch (error) {
      if (!current()) return
      retire()
      startupError.value = error instanceof Error ? error.message : '工作台准备失败，请重试'
    }
  }

  function cancelStartup() {
    retire()
    startupError.value = '工作台准备已取消，可重试或返回登录'
  }

  function dismissStartupSplashImmediate() {
    retire()
    startupVisible.value = false
    appReady.value = true
    startupError.value = ''
  }

  function teardownOnUnmount() { disposed = true; retire() }

  return { startupVisible, appReady, startupError, startupStage, runStartup,
    cancelStartup, dismissStartupSplashImmediate, teardownOnUnmount }
}
