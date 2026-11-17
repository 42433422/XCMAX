/**
 * AIOPEN 虚拟光标星尘拖尾（mature component reuse）。
 *
 * 复用开源库 cursor-effects（MIT, tholman/cursor-effects）的 fairyDustCursor 星尘效果，
 * 通过合成 mousemove/mousedown 事件驱动它跟随程序化移动的虚拟光标。
 * 本文件只做产品侧薄胶水：懒加载、坐标桥接、关闭时销毁。
 */
import type { CursorEffectResult } from 'cursor-effects'

// 与前端主色一致的蓝色星尘，避免默认彩虹色与产品视觉冲突
const TRAIL_COLORS = ['#60a5fa', '#3b82f6', '#93c5fd', '#1d4ed8'] as const

let effect: CursorEffectResult | null = null
let loading: Promise<void> | null = null

function emit(type: 'mousemove' | 'mousedown', x: number, y: number) {
  document.dispatchEvent(
    new MouseEvent(type, {
      clientX: x,
      clientY: y,
      bubbles: true,
      cancelable: true,
      view: window,
    })
  )
}

type TrailConstructor = new (options?: Record<string, unknown>) => CursorEffectResult

/** 首次需要拖尾时才加载库，避免常驻包体。 */
export async function ensureTrail(): Promise<void> {
  // 单测环境没有 canvas 2d 上下文，直接跳过，避免刷屏
  if (import.meta.env.MODE === 'test') return
  if (effect || loading) return loading || undefined
  loading = (async () => {
    try {
      const mod = await import('cursor-effects')
      const Ctor = (mod as unknown as { fairyDustCursor: TrailConstructor }).fairyDustCursor
      effect = new Ctor({ colors: TRAIL_COLORS })
    } catch {
      // 库不可用（旧浏览器 / jsdom）时静默降级为无拖尾
      effect = null
    } finally {
      loading = null
    }
  })()
  return loading
}

/** 光标移动到新坐标时同步驱动粒子拖尾。 */
export function moveTrail(x: number, y: number): void {
  if (!effect) return
  emit('mousemove', x, y)
}

/** 点击落点时触发粒子爆散。 */
export function pulseTrail(x: number, y: number): void {
  if (!effect) return
  emit('mousedown', x, y)
}

export function disableTrail(): void {
  try {
    effect?.destroy()
  } catch {
    /* 已销毁 */
  }
  effect = null
}
