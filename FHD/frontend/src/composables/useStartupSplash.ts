import { ref } from 'vue'

export const STARTUP_READY_TIMEOUT_MS = 20_000

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
