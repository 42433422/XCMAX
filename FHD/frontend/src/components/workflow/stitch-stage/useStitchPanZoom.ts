/**
 * 舞台缩放与中键平移。由 StitchStage.vue 原文机械切分而来（行为保持不变）。
 */
import { computed, nextTick, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { MIDDLE_BUTTON, maxZoom, minZoom, zoomStep } from './stitchStageConstants'
import type { StitchStageProps } from './stitchStageTypes'

export type StitchPanZoomDeps = {
  viewportRef: Ref<HTMLElement | null>
  imgRef: Ref<HTMLImageElement | null>
  composedRootRef: Ref<HTMLElement | null>
  composedOuterHeightPx: ComputedRef<number>
}

export function useStitchPanZoom(props: StitchStageProps, deps: StitchPanZoomDeps) {
  const { viewportRef, imgRef, composedRootRef, composedOuterHeightPx } = deps

  const zoom = ref(1)

  const panX = ref(0)
  const panY = ref(0)
  const middlePanning = ref(false)
  let lastPanClientX = 0
  let lastPanClientY = 0
  let panPointerId: number | null = null

  const zoomPct = computed(() => Math.round(zoom.value * 100))

  const zoomLayerStyle = computed(() => ({
    transform: `translate(${panX.value}px, ${panY.value}px) scale(${zoom.value})`,
    transformOrigin: '0 0',
  }))

  function contentPixelSize(): { w: number; h: number } | null {
    if (props.mode === 'composed') {
      const el = composedRootRef.value
      if (!el || el.offsetWidth < 4) return null
      const h = Math.max(el.offsetHeight, composedOuterHeightPx.value)
      return { w: el.offsetWidth, h }
    }
    const im = imgRef.value
    if (!im?.naturalWidth) return null
    return { w: im.naturalWidth, h: im.naturalHeight }
  }

  function clampPan(): void {
    const vp = viewportRef.value
    const size = contentPixelSize()
    if (!vp || !size) return
    const z = zoom.value
    const sw = size.w * z
    const sh = size.h * z
    const vw = vp.clientWidth
    const vh = vp.clientHeight
    const minPx = Math.min(0, vw - sw)
    const maxPx = Math.max(0, vw - sw)
    const minPy = Math.min(0, vh - sh)
    const maxPy = Math.max(0, vh - sh)
    panX.value = Math.min(maxPx, Math.max(minPx, panX.value))
    panY.value = Math.min(maxPy, Math.max(minPy, panY.value))
  }

  function onViewportPointerDown(e: PointerEvent) {
    if (e.button !== MIDDLE_BUTTON) return
    e.preventDefault()
    middlePanning.value = true
    panPointerId = e.pointerId
    lastPanClientX = e.clientX
    lastPanClientY = e.clientY
    viewportRef.value?.setPointerCapture(e.pointerId)
  }

  function onViewportPointerMove(e: PointerEvent) {
    if (!middlePanning.value || panPointerId !== e.pointerId) return
    e.preventDefault()
    const dx = e.clientX - lastPanClientX
    const dy = e.clientY - lastPanClientY
    lastPanClientX = e.clientX
    lastPanClientY = e.clientY
    panX.value += dx
    panY.value += dy
    clampPan()
  }

  function onViewportPointerUp(e: PointerEvent) {
    if (!middlePanning.value || panPointerId !== e.pointerId) return
    middlePanning.value = false
    panPointerId = null
    try {
      viewportRef.value?.releasePointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
  }

  function onViewportPointerCancel(e: PointerEvent) {
    if (!middlePanning.value || panPointerId !== e.pointerId) return
    middlePanning.value = false
    panPointerId = null
    try {
      viewportRef.value?.releasePointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
  }

  /** 禁止中键触发滚动条/自动滚动等默认行为 */
  function onViewportMouseDown(e: MouseEvent) {
    if (e.button === MIDDLE_BUTTON) {
      e.preventDefault()
    }
  }

  function onViewportAuxClick(e: MouseEvent) {
    if (e.button === MIDDLE_BUTTON) {
      e.preventDefault()
    }
  }

  function computeFitZoom(): void {
    const vp = viewportRef.value
    if (!vp || vp.clientWidth < 48 || vp.clientHeight < 48) return
    const pad = 20
    const vw = Math.max(40, vp.clientWidth - pad * 2)
    const vh = Math.max(40, vp.clientHeight - pad * 2)

    let cw: number
    let ch: number
    if (props.mode === 'composed') {
      const el = composedRootRef.value
      if (!el || el.offsetWidth < 4) {
        void nextTick(() => scheduleFit())
        return
      }
      cw = el.offsetWidth
      ch = Math.max(el.offsetHeight, composedOuterHeightPx.value)
    } else {
      const im = imgRef.value
      if (!im?.naturalWidth) return
      cw = im.naturalWidth
      ch = im.naturalHeight
    }

    /**
     * composed: 允许填满视口的 fit zoom（最高 maxZoom），并把条带在视口中居中——
     * 以前夹在 ≤1 导致 strip 永远只占左上角一小块。tutorial: 仍夹在 ≤1，避免大底图被强行放大失真。
     */
    const upperBound = props.mode === 'composed' ? maxZoom : 1
    const z = Math.min(upperBound, vw / cw, vh / ch)
    const next = Math.max(minZoom, Math.min(maxZoom, Number(z.toFixed(4)) || minZoom))
    zoom.value = next

    const totalVw = vp.clientWidth
    const totalVh = vp.clientHeight
    const sw = cw * next
    const sh = ch * next
    panX.value = sw < totalVw ? Math.max(0, (totalVw - sw) / 2) : 0
    panY.value = sh < totalVh ? Math.max(0, (totalVh - sh) / 2) : 0
    void nextTick(() => clampPan())
  }

  function scheduleFit() {
    void nextTick(() => computeFitZoom())
  }

  function zoomIn() {
    zoom.value = Math.min(maxZoom, Math.round((zoom.value + zoomStep) * 100) / 100)
    void nextTick(() => clampPan())
  }

  function zoomOut() {
    zoom.value = Math.max(minZoom, Math.round((zoom.value - zoomStep) * 100) / 100)
    void nextTick(() => clampPan())
  }

  function resetZoom() {
    computeFitZoom()
  }

  function onZoomInput(e: Event) {
    const v = Number((e.target as HTMLInputElement).value)
    if (!Number.isFinite(v)) return
    zoom.value = Math.min(maxZoom, Math.max(minZoom, v / 100))
    void nextTick(() => clampPan())
  }

  return {
    zoom,
    panX,
    panY,
    middlePanning,
    zoomPct,
    zoomLayerStyle,
    onViewportPointerDown,
    onViewportPointerMove,
    onViewportPointerUp,
    onViewportPointerCancel,
    onViewportMouseDown,
    onViewportAuxClick,
    clampPan,
    computeFitZoom,
    scheduleFit,
    zoomIn,
    zoomOut,
    resetZoom,
    onZoomInput,
  }
}

export type StitchPanZoom = ReturnType<typeof useStitchPanZoom>
