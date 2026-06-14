/**
 * 全景横拼逻辑格：与 `public/yuangong/desk.svg`（96×64）对齐。
 * 运行时以 `useYuangongDeskIntrinsicSize` 读到的 natural 尺寸为准。
 */
export const YUANGONG_CANVAS_W = 96
export const YUANGONG_CANVAS_H = 64

/** 仅用于高清 PNG 素材裁透明边；SVG 默认不裁 */
export const YUANGONG_COMPOSED_TRIM = {
  left: 0,
  right: 0,
  top: 0,
  bottom: 0,
} as const

/** 默认画布（未探测到实际尺寸时） */
export function yuangongComposedBaseSize(): { width: number; height: number } {
  return yuangongComposedBaseSizeFromCanvas(YUANGONG_CANVAS_W, YUANGONG_CANVAS_H)
}

/** 已知 desk 实际像素尺寸时的逻辑格（与素材宽高比一致，contain 时不留左右黑边） */
export function yuangongComposedBaseSizeFromCanvas(canvasW: number, canvasH: number): { width: number; height: number } {
  const t = YUANGONG_COMPOSED_TRIM
  return {
    width: Math.max(1, Math.round(canvasW) - t.left - t.right),
    height: Math.max(1, Math.round(canvasH) - t.top - t.bottom),
  }
}
