/** 语音模式：移动端 / iOS 检测与播放解锁 */

const MOBILE_UA =
  /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i

export function isMobileVoiceDevice(): boolean {
  if (typeof navigator === 'undefined') return false
  return MOBILE_UA.test(navigator.userAgent)
}

export function isIOSVoiceDevice(): boolean {
  if (typeof navigator === 'undefined') return false
  return (
    /iPhone|iPad|iPod/i.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  )
}

/** 移动端底部安全区 + 工作台底栏高度（与 WorkbenchView tabbar 对齐） */
export function mobileVoiceBottomInsetPx(): number {
  if (!isMobileVoiceDevice()) return 0
  let inset = 56
  if (typeof CSS !== 'undefined' && CSS.supports('padding-bottom: env(safe-area-inset-bottom)')) {
    /* env() 由 CSS 处理，JS 仅预留 tabbar 主体高度 */
  }
  return inset
}

let audioUnlockPromise: Promise<void> | null = null

/** iOS / 移动端：在用户手势内解锁 Web Audio，避免 TTS 无声 */
export function unlockVoiceAudioPlayback(): Promise<void> {
  if (typeof window === 'undefined') return Promise.resolve()
  if (audioUnlockPromise) return audioUnlockPromise
  audioUnlockPromise = (async () => {
    try {
      const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      if (!Ctx) return
      const ctx = new Ctx()
      if (ctx.state === 'suspended') await ctx.resume()
      const buf = ctx.createBuffer(1, 1, 22050)
      const src = ctx.createBufferSource()
      src.buffer = buf
      src.connect(ctx.destination)
      src.start(0)
      src.stop(ctx.currentTime + 0.01)
      await ctx.close()
    } catch {
      /* ignore */
    }
  })()
  return audioUnlockPromise
}

export function scrollInputIntoViewOnMobile(el: HTMLElement | null, delayMs = 320): void {
  if (!isMobileVoiceDevice() || !el) return
  window.setTimeout(() => {
    try {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    } catch {
      el.scrollIntoView(true)
    }
  }, delayMs)
}
