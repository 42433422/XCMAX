<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { YuangongStitchHotspot } from '@/constants/yuangongStitchHotspots'
import type { StitchEmployeePlacement } from '@/constants/yuangongStitchPlacements'
import {
  YUANGONG_CANVAS_H,
  YUANGONG_CANVAS_W,
  yuangongComposedBaseSizeFromCanvas,
} from '@/constants/yuangongComposedTrim'
import { YUANGONG_ENTRY_STITCH_PNG } from '@/constants/yuangongAssets'
import { useYuangongDeskIntrinsicSize } from '@/composables/useYuangongDeskIntrinsicSize'
import type { WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'
import {
  ENTERPRISE_ORG_LAYERS,
  countEnterpriseEstablishmentMaxSlots,
  resolveEnterpriseOrgLayer,
} from '@/constants/enterpriseWorkflowEstablishment'
import YuangongStation from '@/components/workflow/YuangongStation.vue'

/** 中键 = auxiliary button */
const MIDDLE_BUTTON = 1

/**
 * 四工位拼接：单格缩放。默认按「舞台视口宽度」反算，使条带 + 外框余量与可视区域接近（全图时 zoom≈100%），
 * 避免固定 3.35 导致画布过宽、长期靠缩小显示。
 */
const COMPOSED_SCALE_MIN = 0.55
const COMPOSED_SCALE_MAX = 5.5
const COMPOSED_SCALE_FALLBACK = 3.35
/** 与 computeFitZoom 内边距一致 */
const COMPOSED_FIT_PAD = 20
/** 与模板 composedStripW 外框水平余量一致 */
const COMPOSED_OUTER_WIDTH_EXTRA = 0
/**
 * 默认让横条几乎铺满舞台宽（保留 ~6% 安全留白以避免轻微溢出 / clampPan 抖动），
 * 同时不超过视口高度的安全上限——避免全景空一大片黑底而像素只占左上角。
 */
const COMPOSED_TARGET_SHRINK = 0.94
/** 视口高度的最大占比上限：strip 高 = baseH × scale，超过此比例则按高反算 scale */
const COMPOSED_TARGET_HEIGHT_RATIO = 0.78
/** 裁边后逻辑格高约 58px，scale 后低于此像素则人物头部与上半身难以辨认 */
const COMPOSED_MIN_STATION_H_PX = 96
/** 相邻工位格水平重叠（px），盖住 contain 左右留白与亚像素竖缝，横条视觉上连成一体 */
const COMPOSED_CELL_OVERLAP_PX = 3
/** 每排八工位：左四无缝 + 过道 + 右四无缝；超过八人换下一排 */
const COMPOSED_SLOTS_PER_ROW = 8
const COMPOSED_LEFT_GROUP_SIZE = 4
/** 左四与右四之间的过道宽度（随格宽缩放） */
const COMPOSED_MID_GAP_MIN_PX = 36
const COMPOSED_MID_GAP_RATIO = 0.48
/** 多排之间的垂直间距（仅超过一排时出现） */
const COMPOSED_ROW_GAP_PX = 10
/** 与 `.stitch-composed` 外框余量一致（无边框/内边距时为 0） */
const COMPOSED_ROOT_VERTICAL_CHROME = 0

/** desk.png 实际像素（naturalWidth/Height）；未加载前为默认 80×58 */
const { deskW, deskH, deskIntrinsicReady } = useYuangongDeskIntrinsicSize()

/**
 * 横拼格宽/高的「逻辑画布」：素材若是高清大图（远大于像素精灵），natural 尺寸会把单格算成上千像素，
 * scale 被下限夹死后仍塞不进视口，表现为工位层空白或错位。此时回退设计稿 80×58 做布局，图片仍 object-fit 缩进格内。
 */
const COMPOSED_DESK_LAYOUT_MAX_DIM = 240

const composedLayoutDeskW = computed(() =>
  deskW.value > COMPOSED_DESK_LAYOUT_MAX_DIM || deskH.value > COMPOSED_DESK_LAYOUT_MAX_DIM
    ? YUANGONG_CANVAS_W
    : deskW.value
)
const composedLayoutDeskH = computed(() =>
  deskW.value > COMPOSED_DESK_LAYOUT_MAX_DIM || deskH.value > COMPOSED_DESK_LAYOUT_MAX_DIM
    ? YUANGONG_CANVAS_H
    : deskH.value
)

/** 舞台视口宽高（ResizeObserver），用于 composed 动态缩放 */
const viewportW = ref(0)
const viewportH = ref(0)
let viewportResizeObserver: ResizeObserver | null = null

const composedBaseSize = computed(() =>
  yuangongComposedBaseSizeFromCanvas(composedLayoutDeskW.value, composedLayoutDeskH.value)
)
const composedBaseW = computed(() => composedBaseSize.value.width)
const composedBaseH = computed(() => composedBaseSize.value.height)

const composedStationScale = computed(() => {
  const bw = composedBaseW.value
  const bh = composedBaseH.value
  const w = viewportW.value
  const h = viewportH.value
  if (w < 64 || bw < 1 || bh < 1) return COMPOSED_SCALE_FALLBACK
  const usableW = Math.max(0, w - COMPOSED_FIT_PAD * 2)
  const labelBandBase = Math.max(22, Math.min(56, bw * 0.12))
  const trackBaseH = bh + labelBandBase

  if (props.mode === 'composed' && props.composedLayout === 'establishment') {
    const n = ENTERPRISE_ORG_LAYERS.length
    const colGapBase = Math.max(12, bw * 0.1)
    const fullRowW = n * bw + (n - 1) * colGapBase
    const widthFit = (usableW - COMPOSED_OUTER_WIDTH_EXTRA) / fullRowW
    let raw = widthFit * COMPOSED_TARGET_SHRINK
    if (h > 64) {
      const usableH = Math.max(0, h - COMPOSED_FIT_PAD * 2 - COMPOSED_ROOT_VERTICAL_CHROME)
      const maxSlots = countEnterpriseEstablishmentMaxSlots(props.desks)
      const totalTracksH = maxSlots * trackBaseH + (maxSlots - 1) * COMPOSED_ROW_GAP_PX
      const heightFit = (usableH * COMPOSED_TARGET_HEIGHT_RATIO) / totalTracksH
      if (heightFit > 0) raw = Math.min(raw, heightFit)
    }
    if (!Number.isFinite(raw) || raw <= 0) raw = COMPOSED_SCALE_FALLBACK
    raw = Math.min(COMPOSED_SCALE_MAX, Math.max(COMPOSED_SCALE_MIN, Number(raw.toFixed(3))))
    const minScaleForHead = COMPOSED_MIN_STATION_H_PX / bh
    raw = Math.max(raw, minScaleForHead)
    return Math.min(COMPOSED_SCALE_MAX, raw)
  }

  const rowCount = Math.max(1, Math.ceil(props.desks.length / COMPOSED_SLOTS_PER_ROW))
  const overlapBase = Math.max(10, bw * 0.44)
  const midGapBase = Math.max(COMPOSED_MID_GAP_MIN_PX, bw * COMPOSED_MID_GAP_RATIO)
  const groupW = COMPOSED_LEFT_GROUP_SIZE * bw - (COMPOSED_LEFT_GROUP_SIZE - 1) * overlapBase
  const fullRowW = groupW + midGapBase + groupW
  const widthFit = (usableW - COMPOSED_OUTER_WIDTH_EXTRA) / fullRowW
  let raw = widthFit * COMPOSED_TARGET_SHRINK
  if (h > 64) {
    const usableH = Math.max(0, h - COMPOSED_FIT_PAD * 2 - COMPOSED_ROOT_VERTICAL_CHROME)
    const labelBandBase = Math.max(22, Math.min(56, bw * 0.12))
    const trackBaseH = bh + labelBandBase
    const totalTracksH = rowCount * trackBaseH + (rowCount - 1) * COMPOSED_ROW_GAP_PX
    const heightFit = (usableH * COMPOSED_TARGET_HEIGHT_RATIO) / totalTracksH
    if (heightFit > 0) raw = Math.min(raw, heightFit)
  }
  if (!Number.isFinite(raw) || raw <= 0) raw = COMPOSED_SCALE_FALLBACK
  raw = Math.min(COMPOSED_SCALE_MAX, Math.max(COMPOSED_SCALE_MIN, Number(raw.toFixed(3))))
  const minScaleForHead = COMPOSED_MIN_STATION_H_PX / bh
  raw = Math.max(raw, minScaleForHead)
  return Math.min(COMPOSED_SCALE_MAX, raw)
})

const composedCellW = computed(() => composedBaseW.value * composedStationScale.value)

/** 同组 flex 负 margin 重叠比例（须足够大，且工位图可溢出格宽） */
const composedCellOverlapPx = computed(() =>
  Math.max(10, Math.round(composedCellW.value * 0.44))
)

const composedMidGapPx = computed(() =>
  Math.max(COMPOSED_MID_GAP_MIN_PX, Math.round(composedCellW.value * COMPOSED_MID_GAP_RATIO))
)

const isEstablishmentLayout = computed(
  () => props.mode === 'composed' && props.composedLayout === 'establishment'
)

const composedEstablishmentColGap = computed(() =>
  Math.max(12, Math.round(composedCellW.value * 0.1))
)

const composedStationH = computed(() => composedBaseH.value * composedStationScale.value)
/** 底部名称条与字号随单格宽度变化，避免大图时 7px 字看不见 */
const composedLabelBandH = computed(() => {
  const w = composedCellW.value
  if (w < 8) return 26
  return Math.max(22, Math.min(56, Math.round(w * 0.12)))
})
const composedLabelFontPx = computed(() => {
  const w = composedCellW.value
  if (w < 8) return 9
  return Math.max(8, Math.min(16, Math.round(w * 0.038)))
})
const composedTrackH = computed(() => composedStationH.value + composedLabelBandH.value)

const props = withDefaults(
  defineProps<{
    /** tutorial：底图 + 可选锚点叠层；composed：每排左四+过道+右四，按人数自动多排 */
    mode?: 'tutorial' | 'composed'
    imageSrc: string
    selectedEmpId: string | null
    hotspots: YuangongStitchHotspot[]
    /** 用于热点按钮的无障碍名称解析 */
    resolveHotspotLabel?: (empId: string) => string
    /** 与右侧列表同源；tutorial 模式可在图上叠层，composed 模式用于四格 */
    desks?: WorkflowEmployeeDeskRow[]
    stationPlacements?: StitchEmployeePlacement[]
    resolveStationAriaLabel?: (empId: string) => string
    /**
     * composed：是否在条带下铺一张横向全景（默认 `stitch-tutorial.png`，可用 `imageSrc` 覆盖）。
     * 为 false 时仍用逐格 desk 叠在渐变底上。
     */
    useComposedPanorama?: boolean
    /** pixel：像素风舞台；office：与员工空间 / 六部门浅色主题对齐 */
    visualSkin?: 'pixel' | 'office'
    /**
     * composed 布局：strip = 每排左四+过道+右四横拼；establishment = 企业六编制列式工位图。
     */
    composedLayout?: 'strip' | 'establishment'
  }>(),
  {
    mode: 'tutorial',
    desks: () => [],
    stationPlacements: () => [],
    useComposedPanorama: true,
    visualSkin: 'pixel',
    composedLayout: 'strip',
  }
)

function composedGroupStripWidth(count: number): number {
  if (count <= 0) return 0
  const cw = composedCellW.value
  const overlap = composedCellOverlapPx.value
  return cw * count - (count - 1) * overlap
}

function composedRowGroups(rowSlots: { empId: string; row: WorkflowEmployeeDeskRow }[]) {
  return {
    left: rowSlots.slice(0, COMPOSED_LEFT_GROUP_SIZE),
    right: rowSlots.slice(COMPOSED_LEFT_GROUP_SIZE),
  }
}

function composedCellOverlapMargin(idx: number): string {
  return idx > 0 ? `-${composedCellOverlapPx.value}px` : '0'
}

function composedRowStripWidth(cellCount: number): number {
  if (cellCount <= 0) return 1
  const cw = composedCellW.value
  const overlap = composedCellOverlapPx.value
  const leftCount = Math.min(cellCount, COMPOSED_LEFT_GROUP_SIZE)
  const rightCount = Math.max(0, cellCount - COMPOSED_LEFT_GROUP_SIZE)
  let w = 0
  if (leftCount > 0) {
    w += cw * leftCount - (leftCount - 1) * overlap
  }
  if (rightCount > 0) {
    if (leftCount >= COMPOSED_LEFT_GROUP_SIZE) {
      w += composedMidGapPx.value
    }
    w += cw * rightCount - (rightCount - 1) * overlap
  }
  return Math.max(1, w)
}

const emit = defineEmits<{
  (e: 'select', empId: string): void
  (e: 'image-error'): void
}>()

const viewportRef = ref<HTMLElement | null>(null)
const imgRef = ref<HTMLImageElement | null>(null)
const composedRootRef = ref<HTMLElement | null>(null)

const isComposed = computed(() => props.mode === 'composed')

type ComposedBackdropState = 'idle' | 'ready' | 'error'
const composedBackdropState = ref<ComposedBackdropState>('idle')

const composedPanoramaUrl = computed(() => {
  if (props.mode !== 'composed' || props.useComposedPanorama === false) return ''
  const trimmed = (props.imageSrc || '').trim()
  return trimmed || YUANGONG_ENTRY_STITCH_PNG
})

const showComposedBackdrop = computed(() => isComposed.value && Boolean(composedPanoramaUrl.value))

/** 全景底图加载成功后，空闲格不再叠整张 desk，避免与底图「双工位」 */
const composedIdleDeskVisible = computed(
  () => !showComposedBackdrop.value || composedBackdropState.value !== 'ready'
)

watch(composedPanoramaUrl, () => {
  composedBackdropState.value = 'idle'
})

watch(
  () => props.mode,
  (m) => {
    if (m !== 'composed') composedBackdropState.value = 'idle'
  }
)

const zoom = ref(1)
const minZoom = 0.25
const maxZoom = 2.5
const zoomStep = 0.25

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

function onComposedBackdropLoad() {
  composedBackdropState.value = 'ready'
  void nextTick(() => scheduleFit())
}

function onComposedBackdropError() {
  composedBackdropState.value = 'error'
  emit('image-error')
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

function onImgLoad() {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => scheduleFit())
  })
}

function updateViewportSize(): void {
  const el = viewportRef.value
  if (el) {
    viewportW.value = el.clientWidth
    viewportH.value = el.clientHeight
  }
}

/** 缓存图已就绪时（含磁盘缓存）补一次适配；composed 在布局后量宽 */
onMounted(() => {
  void nextTick(() => {
    updateViewportSize()
    const el = viewportRef.value
    if (el && typeof ResizeObserver !== 'undefined') {
      viewportResizeObserver = new ResizeObserver(() => {
        updateViewportSize()
        void nextTick(() => scheduleFit())
      })
      viewportResizeObserver.observe(el)
    }
  })
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      if (props.mode === 'composed') {
        scheduleFit()
      } else if (imgRef.value?.complete && imgRef.value.naturalWidth) {
        scheduleFit()
      }
    })
  })
})

onUnmounted(() => {
  viewportResizeObserver?.disconnect()
  viewportResizeObserver = null
})

function hotspotLabel(h: YuangongStitchHotspot): string {
  if (h.label) return h.label
  if (props.resolveHotspotLabel) return props.resolveHotspotLabel(h.empId)
  return `选择员工 ${h.empId}`
}

function hotspotStyle(h: YuangongStitchHotspot) {
  return {
    left: `${h.leftPct}%`,
    top: `${h.topPct}%`,
    width: `${h.widthPct}%`,
    height: `${h.heightPct}%`,
  }
}

const placedStations = computed(() => {
  const list: { placement: StitchEmployeePlacement; row: WorkflowEmployeeDeskRow }[] = []
  for (const placement of props.stationPlacements) {
    const row = props.desks.find((d) => d.empId === placement.empId)
    if (row) list.push({ placement, row })
  }
  return list
})

function placementStyle(p: StitchEmployeePlacement) {
  const s = p.scale ?? 4
  return {
    left: `${p.leftPct}%`,
    top: `${p.topPct}%`,
    transform: `translate(-50%, -100%) scale(${s})`,
    transformOrigin: '50% 100%',
  }
}

function stationBusy(row: WorkflowEmployeeDeskRow): boolean {
  if (!row.enabled) return false
  return row.snapshot?.visuallyBusy === true
}

function stationAriaLabel(empId: string, row: WorkflowEmployeeDeskRow): string {
  if (props.resolveStationAriaLabel) return props.resolveStationAriaLabel(empId)
  return `员工 ${row.shortName}`
}

const composedSlots = computed(() =>
  props.desks.map((row) => ({ empId: row.empId, row }))
)

const composedRows = computed(() => {
  const slots = composedSlots.value
  const rows: { empId: string; row: WorkflowEmployeeDeskRow }[][] = []
  for (let i = 0; i < slots.length; i += COMPOSED_SLOTS_PER_ROW) {
    rows.push(slots.slice(i, i + COMPOSED_SLOTS_PER_ROW))
  }
  return rows
})

const establishmentColumns = computed(() => {
  const slots = composedSlots.value
  const byZone = new Map<string, { empId: string; row: WorkflowEmployeeDeskRow }[]>()
  for (const z of ENTERPRISE_ORG_LAYERS) {
    byZone.set(z.id, [])
  }
  for (const slot of slots) {
    const zid = resolveEnterpriseOrgLayer(
      slot.empId,
      slot.row.shortName,
      slot.row.panelTitle
    )
    const list = byZone.get(zid) ?? byZone.get('management')!
    list.push(slot)
  }
  return ENTERPRISE_ORG_LAYERS.map((zone) => ({
    zone,
    slots: byZone.get(zone.id) ?? [],
  }))
})

const establishmentMaxSlots = computed(() => {
  if (!isEstablishmentLayout.value) return 1
  return countEnterpriseEstablishmentMaxSlots(props.desks)
})

const composedStripW = computed(() => {
  if (isEstablishmentLayout.value) {
    const n = ENTERPRISE_ORG_LAYERS.length
    const cw = composedCellW.value
    const gap = composedEstablishmentColGap.value
    return n * cw + (n - 1) * gap
  }
  const rows = composedRows.value
  const fullRowW = composedRowStripWidth(COMPOSED_SLOTS_PER_ROW)
  if (!rows.length) return fullRowW
  return Math.max(fullRowW, ...rows.map((r) => composedRowStripWidth(r.length)))
})
const composedRowsAreaH = computed(() => {
  if (isEstablishmentLayout.value) {
    const maxSlots = establishmentMaxSlots.value
    if (maxSlots <= 0) return composedTrackH.value
    return maxSlots * composedTrackH.value + (maxSlots - 1) * COMPOSED_ROW_GAP_PX
  }
  const n = composedRows.value.length
  if (n === 0) return composedTrackH.value
  return n * composedTrackH.value + (n - 1) * COMPOSED_ROW_GAP_PX
})
const composedOuterHeightPx = computed(() => composedRowsAreaH.value + COMPOSED_ROOT_VERTICAL_CHROME)

/** 单格内工位层：用最终像素宽高铺满格宽，避免父级 transform: scale 与布局/子项百分比不一致 */
const composedStationWrapStyle = computed(() => ({
  height: `${composedStationH.value}px`,
}))

/** 换图后待 load 再适配全图 */
watch(
  () => props.imageSrc,
  () => {
    if (props.mode === 'composed') return
    void nextTick(() => {
      if (imgRef.value?.complete && imgRef.value.naturalWidth) {
        scheduleFit()
      }
    })
  }
)

watch(
  () => props.mode,
  () => {
    void nextTick(() => scheduleFit())
  }
)

watch(
  () => props.desks.map((d) => d.empId).join('\0'),
  () => {
    if (props.mode === 'composed') {
      void nextTick(() => scheduleFit())
    }
  }
)

watch(
  () => props.desks.map((d) => `${d.empId}:${d.enabled}:${d.snapshot?.visuallyBusy}`).join('|'),
  () => {
    if (props.mode === 'composed') {
      void nextTick(() => clampPan())
    }
  }
)

watch([deskW, deskH], () => {
  if (props.mode !== 'composed') return
  void nextTick(() => scheduleFit())
})

watch(deskIntrinsicReady, (ready) => {
  if (!ready || props.mode !== 'composed') return
  void nextTick(() => scheduleFit())
})

watch(composedStationScale, () => {
  if (props.mode !== 'composed') return
  void nextTick(() => scheduleFit())
})

watch(composedRowsAreaH, () => {
  if (props.mode !== 'composed') return
  void nextTick(() => scheduleFit())
})

watch(
  () => props.composedLayout,
  () => {
    if (props.mode !== 'composed') return
    void nextTick(() => scheduleFit())
  }
)
</script>

<template>
  <div
    class="stitch-stage"
    :class="{ 'stitch-stage--office': props.visualSkin === 'office' }"
    role="region"
    :aria-label="
      isComposed
        ? isEstablishmentLayout
          ? '企业六编制工位图：按业务域分列展示已安装 Mod 员工；中键拖移、工具栏缩放'
          : '多排工位拼接全景：每排左四与右四之间有过道，组内无缝横拼；鼠标中键拖动平移，工具栏缩放；点击工位可选中员工'
        : '拼接图舞台：背景图与实时工位叠层；鼠标中键拖动平移，工具栏缩放；热点与工位可点选员工'
    "
  >
    <div class="stitch-stage-toolbar" role="toolbar" aria-label="缩放与中键平移说明">
      <button type="button" class="stitch-stage-btn" :disabled="zoom <= minZoom" @click="zoomOut">
        缩小
      </button>
      <label class="stitch-stage-zoom-label">
        <span class="stitch-stage-sr">缩放比例</span>
        <input
          class="stitch-stage-range"
          type="range"
          :min="minZoom * 100"
          :max="maxZoom * 100"
          :step="zoomStep * 100"
          :value="zoom * 100"
          @input="onZoomInput"
        />
        <span class="stitch-stage-zoom-readout" aria-hidden="true">{{ zoomPct }}%</span>
      </label>
      <button type="button" class="stitch-stage-btn" :disabled="zoom >= maxZoom" @click="zoomIn">
        放大
      </button>
      <button type="button" class="stitch-stage-btn stitch-stage-btn--ghost" title="缩放至可见整图" @click="resetZoom">
        全图
      </button>
      <span class="stitch-stage-hint" aria-hidden="true">中键拖移</span>
    </div>

    <div
      ref="viewportRef"
      class="stitch-stage-viewport"
      :class="{ 'stitch-stage-viewport--grabbing': middlePanning }"
      tabindex="0"
      @pointerdown="onViewportPointerDown"
      @pointermove="onViewportPointerMove"
      @pointerup="onViewportPointerUp"
      @pointercancel="onViewportPointerCancel"
      @mousedown="onViewportMouseDown"
      @auxclick="onViewportAuxClick"
    >
      <div class="stitch-stage-zoom-layer" :style="zoomLayerStyle">
        <div
          v-if="isComposed"
          ref="composedRootRef"
          class="stitch-composed"
          :style="{
            width: `${composedStripW}px`,
            minHeight: `${composedOuterHeightPx}px`,
            height: `${composedOuterHeightPx}px`,
          }"
        >
          <div class="stitch-composed-strip" role="presentation">
            <div
              class="stitch-composed-scene"
              :style="{
                width: `${composedStripW}px`,
                height: `${composedRowsAreaH}px`,
                '--stitch-composed-label-font': `${composedLabelFontPx}px`,
              }"
            >
              <img
                v-if="showComposedBackdrop"
                :key="composedPanoramaUrl"
                class="stitch-composed-backdrop stitch-composed-backdrop--scene"
                :src="composedPanoramaUrl"
                alt=""
                decoding="async"
                draggable="false"
                @load="onComposedBackdropLoad"
                @error="onComposedBackdropError"
              />
              <p v-if="!composedSlots.length" class="stitch-composed-empty">
                暂无工作流员工；请从 MOD 商店安装工作流员工 Mod 后刷新。
              </p>
              <div
                v-else-if="isEstablishmentLayout"
                class="stitch-establishment"
                :style="{
                  width: `${composedStripW}px`,
                  height: `${composedRowsAreaH}px`,
                  gap: `${composedEstablishmentColGap}px`,
                }"
              >
                <div
                  v-for="col in establishmentColumns"
                  :key="col.zone.id"
                  class="stitch-establishment-col"
                  :style="{
                    width: `${composedCellW}px`,
                    '--zone-color': col.zone.color,
                  }"
                >
                  <header class="stitch-establishment-head">
                    <span class="stitch-establishment-code">{{ col.zone.code }}</span>
                    <span class="stitch-establishment-name">{{ col.zone.label }}</span>
                    <span class="stitch-establishment-badge">{{ col.slots.length }}</span>
                  </header>
                  <p class="stitch-establishment-desc">{{ col.zone.desc }}</p>
                  <div class="stitch-establishment-body">
                    <p v-if="!col.slots.length" class="stitch-establishment-empty">暂无员工 Mod</p>
                    <div
                      v-for="(slot, idx) in col.slots"
                      :key="'est-' + slot.empId"
                      class="stitch-composed-cell stitch-establishment-cell"
                      role="button"
                      tabindex="0"
                      :aria-label="stationAriaLabel(slot.empId, slot.row)"
                      :aria-current="selectedEmpId === slot.empId ? 'true' : undefined"
                      :style="{
                        width: `${composedCellW}px`,
                        height: `${composedTrackH}px`,
                        marginTop: idx > 0 ? `${COMPOSED_ROW_GAP_PX}px` : '0',
                        zIndex: selectedEmpId === slot.empId ? 20 : idx + 1,
                      }"
                      @click.stop="emit('select', slot.empId)"
                      @keydown.enter.prevent="emit('select', slot.empId)"
                    >
                      <div
                        class="stitch-composed-station-wrap"
                        :class="{ 'stitch-composed-station-wrap--selected': selectedEmpId === slot.empId }"
                        :style="composedStationWrapStyle"
                      >
                        <span class="stitch-composed-station-vis" aria-hidden="true">
                          <YuangongStation
                            pixel-layout="composed"
                            :composed-idle-desk-visible="composedIdleDeskVisible"
                            :enabled="slot.row.enabled"
                            :busy="stationBusy(slot.row)"
                            :ariaLabel="stationAriaLabel(slot.empId, slot.row)"
                          />
                        </span>
                      </div>
                      <p class="stitch-composed-label" :title="slot.row.panelTitle">{{ slot.row.shortName }}</p>
                    </div>
                  </div>
                </div>
              </div>
              <template v-else>
              <div
                v-for="(rowSlots, rowIdx) in composedRows"
                :key="'cmp-row-' + rowIdx"
                class="stitch-composed-row"
                :style="{
                  width: `${composedRowStripWidth(rowSlots.length)}px`,
                  height: `${composedTrackH}px`,
                  top: `${rowIdx * (composedTrackH + COMPOSED_ROW_GAP_PX)}px`,
                  left: `${(composedStripW - composedRowStripWidth(rowSlots.length)) / 2}px`,
                }"
              >
                <div class="stitch-composed-group">
                  <div
                    v-for="(slot, idx) in composedRowGroups(rowSlots).left"
                    :key="'cmp-' + slot.empId"
                    class="stitch-composed-cell"
                    role="button"
                    tabindex="0"
                    :aria-label="stationAriaLabel(slot.empId, slot.row)"
                    :aria-current="selectedEmpId === slot.empId ? 'true' : undefined"
                    :style="{
                      width: `${composedCellW}px`,
                      height: `${composedTrackH}px`,
                      marginLeft: composedCellOverlapMargin(idx),
                      zIndex:
                        selectedEmpId === slot.empId
                          ? 20
                          : rowIdx * COMPOSED_SLOTS_PER_ROW + idx + 1,
                    }"
                    @click.stop="emit('select', slot.empId)"
                    @keydown.enter.prevent="emit('select', slot.empId)"
                  >
                    <div
                      class="stitch-composed-station-wrap"
                      :class="{ 'stitch-composed-station-wrap--selected': selectedEmpId === slot.empId }"
                      :style="composedStationWrapStyle"
                    >
                      <span class="stitch-composed-station-vis" aria-hidden="true">
                        <YuangongStation
                          pixel-layout="composed"
                          :composed-idle-desk-visible="composedIdleDeskVisible"
                          :enabled="slot.row.enabled"
                          :busy="stationBusy(slot.row)"
                          :ariaLabel="stationAriaLabel(slot.empId, slot.row)"
                        />
                      </span>
                    </div>
                    <p class="stitch-composed-label" :title="slot.row.panelTitle">{{ slot.row.shortName }}</p>
                  </div>
                </div>
                <div
                  v-if="composedRowGroups(rowSlots).right.length"
                  class="stitch-composed-aisle"
                  :style="{ width: `${composedMidGapPx}px` }"
                  aria-hidden="true"
                />
                <div v-if="composedRowGroups(rowSlots).right.length" class="stitch-composed-group">
                  <div
                    v-for="(slot, idx) in composedRowGroups(rowSlots).right"
                    :key="'cmp-' + slot.empId"
                    class="stitch-composed-cell"
                    role="button"
                    tabindex="0"
                    :aria-label="stationAriaLabel(slot.empId, slot.row)"
                    :aria-current="selectedEmpId === slot.empId ? 'true' : undefined"
                    :style="{
                      width: `${composedCellW}px`,
                      height: `${composedTrackH}px`,
                      marginLeft: composedCellOverlapMargin(idx),
                      zIndex:
                        selectedEmpId === slot.empId
                          ? 20
                          : rowIdx * COMPOSED_SLOTS_PER_ROW + COMPOSED_LEFT_GROUP_SIZE + idx + 1,
                    }"
                    @click.stop="emit('select', slot.empId)"
                    @keydown.enter.prevent="emit('select', slot.empId)"
                  >
                    <div
                      class="stitch-composed-station-wrap"
                      :class="{ 'stitch-composed-station-wrap--selected': selectedEmpId === slot.empId }"
                      :style="composedStationWrapStyle"
                    >
                      <span class="stitch-composed-station-vis" aria-hidden="true">
                        <YuangongStation
                          pixel-layout="composed"
                          :composed-idle-desk-visible="composedIdleDeskVisible"
                          :enabled="slot.row.enabled"
                          :busy="stationBusy(slot.row)"
                          :ariaLabel="stationAriaLabel(slot.empId, slot.row)"
                        />
                      </span>
                    </div>
                    <p class="stitch-composed-label" :title="slot.row.panelTitle">{{ slot.row.shortName }}</p>
                  </div>
                </div>
              </div>
              </template>
            </div>
          </div>
        </div>
        <div v-else class="stitch-stage-img-shell">
          <img
            ref="imgRef"
            class="stitch-stage-img"
            :src="imageSrc"
            alt=""
            decoding="async"
            draggable="false"
            @load="onImgLoad"
            @error="emit('image-error')"
          />
          <div
            v-for="{ placement, row } in placedStations"
            :key="'st-' + placement.empId"
            class="stitch-stage-station"
            :class="{ 'stitch-stage-station--selected': selectedEmpId === placement.empId }"
            :style="placementStyle(placement)"
            role="button"
            tabindex="0"
            :aria-label="stationAriaLabel(placement.empId, row)"
            :aria-current="selectedEmpId === placement.empId ? 'true' : undefined"
            @click.stop="emit('select', placement.empId)"
            @keydown.enter.prevent="emit('select', placement.empId)"
          >
            <span class="stitch-stage-station-vis" aria-hidden="true">
              <YuangongStation
                :enabled="row.enabled"
                :busy="stationBusy(row)"
                :ariaLabel="stationAriaLabel(placement.empId, row)"
              />
            </span>
          </div>
          <button
            v-for="h in hotspots"
            :key="h.empId"
            type="button"
            class="stitch-stage-hotspot"
            :class="{ 'stitch-stage-hotspot--selected': selectedEmpId === h.empId }"
            :style="hotspotStyle(h)"
            :aria-label="hotspotLabel(h)"
            :aria-pressed="selectedEmpId === h.empId"
            @click="emit('select', h.empId)"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap');

.stitch-stage {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  flex: 1;
}

.stitch-stage-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-family: 'Press Start 2P', ui-monospace, monospace;
}

.stitch-stage-btn {
  padding: 8px 10px;
  border-radius: 0;
  border: 3px solid #64748b;
  box-shadow: inset 0 -3px 0 rgba(0, 0, 0, 0.35);
  background: #334155;
  color: #f1f5f9;
  font-size: 8px;
  line-height: 1.4;
  letter-spacing: 0.02em;
  cursor: pointer;
  image-rendering: pixelated;
}

.stitch-stage-btn:hover:not(:disabled) {
  background: #475569;
  color: #fff;
}

.stitch-stage-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.stitch-stage-btn--ghost {
  border-style: solid;
  border-color: #94a3b8;
}

.stitch-stage-zoom-label {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1 1 160px;
  min-width: 0;
  color: #cbd5e1;
  font-size: 7px;
  line-height: 1.5;
}

.stitch-stage-range {
  flex: 1;
  min-width: 80px;
  accent-color: #38bdf8;
}

.stitch-stage-zoom-readout {
  min-width: 3rem;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.stitch-stage-hint {
  margin-left: 4px;
  font-size: 6px;
  line-height: 1.5;
  color: #94a3b8;
  white-space: nowrap;
}

.stitch-stage-sr {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.stitch-stage-viewport {
  flex: 1;
  min-height: 200px;
  min-width: 0;
  overflow: hidden;
  border-radius: 0;
  border: 4px solid #1e293b;
  box-shadow: inset 0 0 0 2px #0f172a;
  background: #020617;
  cursor: grab;
  touch-action: none;
  user-select: none;
  -webkit-user-select: none;
}

.stitch-stage-viewport--grabbing {
  cursor: grabbing;
}

.stitch-stage-viewport:focus-visible {
  outline: 2px solid #38bdf8;
  outline-offset: 2px;
}

.stitch-stage-zoom-layer {
  display: inline-block;
  vertical-align: top;
}

.stitch-composed {
  box-sizing: border-box;
  padding: 0;
  margin: 0;
  background: transparent;
  border: none;
  box-shadow: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  line-height: 0;
}

.stitch-composed-strip {
  margin: 0;
  padding: 0;
}

.stitch-composed-scene {
  position: relative;
  margin: 0 auto;
}

.stitch-composed-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  padding: 16px;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 8px;
  line-height: 1.65;
  color: #94a3b8;
  text-align: center;
}

/* 一排：左组 flex 横拼 + 过道留白 + 右组 flex 横拼 */
.stitch-composed-row {
  position: absolute;
  display: flex;
  flex-direction: row;
  align-items: stretch;
  margin: 0;
  padding: 0;
  overflow: visible;
  background: linear-gradient(180deg, #1e293b 0%, #0f172a 42%, #020617 100%);
  border: 2px solid #1e293b;
  box-shadow: inset 0 -3px 0 rgba(0, 0, 0, 0.35);
  image-rendering: pixelated;
  --stitch-composed-label-font: 9px;
}

.stitch-composed-group {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  flex: 0 0 auto;
  background: #c4b5a0;
  box-shadow: inset 0 -3px 0 rgba(107, 83, 68, 0.35);
}

.stitch-composed-aisle {
  flex: 0 0 auto;
  align-self: stretch;
  background: transparent;
}

.stitch-composed-backdrop--scene {
  position: absolute;
  left: 0;
  top: 0;
  z-index: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center bottom;
  pointer-events: none;
  user-select: none;
  -webkit-user-drag: none;
  image-rendering: pixelated;
  image-rendering: crisp-edges;
}

.stitch-composed-backdrop {
  position: absolute;
  left: 0;
  top: 0;
  z-index: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center bottom;
  pointer-events: none;
  user-select: none;
  -webkit-user-drag: none;
  image-rendering: pixelated;
  image-rendering: crisp-edges;
}

.stitch-composed-cell {
  position: relative;
  flex: 0 0 auto;
  box-sizing: border-box;
  margin-top: 0;
  margin-bottom: 0;
  padding: 0;
  border: none;
  cursor: pointer;
  outline: none;
  background: transparent;
}

.stitch-composed-cell:hover .stitch-composed-station-vis {
  filter: brightness(1.12);
}

.stitch-composed-cell:focus-visible {
  z-index: 2;
}

.stitch-composed-cell:focus-visible .stitch-composed-station-vis {
  box-shadow: 0 0 0 2px #facc15;
}

.stitch-composed-station-wrap--selected {
  z-index: 1;
}

.stitch-composed-station-wrap--selected .stitch-composed-station-vis {
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.95);
}

.stitch-composed-station-wrap {
  position: absolute;
  z-index: 0;
  left: 0;
  right: 0;
  top: 0;
  margin: 0;
  padding: 0;
  overflow: visible;
  box-sizing: border-box;
}

.stitch-composed-station-vis {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 1px;
  overflow: visible;
}

.stitch-composed-station-vis :deep(.yuangong-stack) {
  pointer-events: none;
}

.stitch-composed-label {
  position: absolute;
  z-index: 3;
  left: 0;
  right: 0;
  bottom: 3px;
  margin: 0;
  padding: 2px 4px 1px;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: var(--stitch-composed-label-font, 9px);
  line-height: 1.35;
  color: #e2e8f0;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  pointer-events: none;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.85);
  background: linear-gradient(180deg, transparent 0%, rgba(2, 6, 23, 0.72) 55%, rgba(2, 6, 23, 0.88) 100%);
}

.stitch-stage-img-shell {
  position: relative;
  display: inline-block;
  vertical-align: top;
  line-height: 0;
}

.stitch-stage-station {
  position: absolute;
  z-index: 2;
  pointer-events: auto;
  cursor: pointer;
  outline: none;
}

.stitch-stage-station:focus-visible {
  box-shadow: 0 0 0 3px rgba(250, 204, 21, 0.9);
}

.stitch-stage-station--selected {
  filter: drop-shadow(0 0 6px rgba(56, 189, 248, 0.85));
}

.stitch-stage-station :deep(.yuangong-stack) {
  pointer-events: none;
}

.stitch-stage-station-vis {
  display: block;
}

.stitch-stage-img {
  display: block;
  width: auto;
  height: auto;
  max-width: none;
  image-rendering: pixelated;
  image-rendering: crisp-edges;
}

.stitch-stage-hotspot {
  position: absolute;
  z-index: 4;
  margin: 0;
  padding: 0;
  border: 2px solid transparent;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  box-sizing: border-box;
}

.stitch-stage-hotspot:hover {
  border-color: rgba(147, 197, 253, 0.55);
  background: rgba(147, 197, 253, 0.12);
}

.stitch-stage-hotspot:focus {
  outline: none;
}

.stitch-stage-hotspot:focus-visible {
  border-color: #fff;
  box-shadow: 0 0 0 2px rgba(15, 23, 42, 0.9);
}

.stitch-stage-hotspot--selected {
  border-color: rgba(96, 165, 250, 0.95);
  background: rgba(59, 130, 246, 0.18);
}

/* —— Office 浅色皮肤：与员工空间 / 六部门编制图对齐 —— */
.stitch-stage--office .stitch-stage-toolbar {
  font-family: ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif;
  gap: 8px;
}

.stitch-stage--office .stitch-stage-btn {
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid #d1d5db;
  box-shadow: none;
  background: #fff;
  color: #374151;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.35;
  letter-spacing: normal;
}

.stitch-stage--office .stitch-stage-btn:hover:not(:disabled) {
  background: #f3f4f6;
  color: #111827;
}

.stitch-stage--office .stitch-stage-btn--ghost {
  border-color: #e5e7eb;
  background: #f9fafb;
  color: #6b7280;
}

.stitch-stage--office .stitch-stage-zoom-label {
  color: #6b7280;
  font-size: 12px;
  font-weight: 500;
}

.stitch-stage--office .stitch-stage-zoom-readout {
  color: #111827;
  font-size: 12px;
  font-weight: 600;
  font-family: ui-monospace, monospace;
}

.stitch-stage--office .stitch-stage-range {
  accent-color: #0b72d9;
}

.stitch-stage--office .stitch-stage-viewport {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.85);
  background:
    radial-gradient(ellipse at 50% 100%, rgba(11, 114, 217, 0.07) 0%, transparent 58%),
    linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
}

.stitch-stage--office .stitch-stage-viewport:focus-visible {
  outline: 2px solid #0b72d9;
  outline-offset: 2px;
}

.stitch-stage--office .stitch-composed-row {
  background:
    radial-gradient(ellipse at 50% 100%, rgba(11, 114, 217, 0.06) 0%, transparent 62%),
    linear-gradient(180deg, #eef2ff 0%, #f8fafc 55%, #ffffff 100%);
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  box-shadow: none;
}

.stitch-stage--office .stitch-composed-empty {
  color: #6b7280;
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: 13px;
  line-height: 1.5;
}

.stitch-stage--office .stitch-composed-label {
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: var(--stitch-composed-label-font, 10px);
  font-weight: 600;
  color: #374151;
  text-shadow: none;
  background: linear-gradient(180deg, transparent 0%, rgba(255, 255, 255, 0.82) 45%, rgba(255, 255, 255, 0.96) 100%);
}

.stitch-stage--office .stitch-composed-cell:focus-visible .stitch-composed-station-vis {
  box-shadow: 0 0 0 2px #0b72d9;
}

.stitch-stage--office .stitch-composed-station-wrap--selected .stitch-composed-station-vis {
  box-shadow: 0 0 0 2px rgba(11, 114, 217, 0.85);
}

/* —— 企业六编制列式工位图 —— */
.stitch-establishment {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  justify-content: center;
  margin: 0 auto;
}

.stitch-establishment-col {
  flex: 0 0 auto;
  box-sizing: border-box;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--zone-color, #64748b) 28%, #e5e7eb);
  background: color-mix(in srgb, var(--zone-color, #64748b) 6%, #ffffff);
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.8) inset;
  padding: 8px 6px 10px;
  min-height: 120px;
}

.stitch-establishment-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 2px 4px;
  min-width: 0;
}

.stitch-establishment-code {
  flex: 0 0 auto;
  font-size: 10px;
  font-weight: 800;
  font-family: ui-monospace, monospace;
  color: var(--zone-color, #475569);
  background: color-mix(in srgb, var(--zone-color, #64748b) 14%, #fff);
  border-radius: 4px;
  padding: 2px 5px;
  line-height: 1.3;
}

.stitch-establishment-name {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 12px;
  font-weight: 700;
  color: #111827;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stitch-establishment-badge {
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: #64748b;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  padding: 1px 7px;
  line-height: 1.45;
}

.stitch-establishment-desc {
  margin: 0 2px 8px;
  font-size: 10px;
  line-height: 1.45;
  color: #6b7280;
}

.stitch-establishment-body {
  display: flex;
  flex-direction: column;
  align-items: stretch;
}

.stitch-establishment-empty {
  margin: 0;
  padding: 16px 8px;
  font-size: 11px;
  line-height: 1.5;
  color: #9ca3af;
  text-align: center;
  border-radius: 8px;
  border: 1px dashed #e5e7eb;
  background: rgba(255, 255, 255, 0.65);
}

.stitch-establishment-cell {
  margin-left: 0 !important;
}

.stitch-stage--office .stitch-establishment-col {
  background: color-mix(in srgb, var(--zone-color, #64748b) 5%, #ffffff);
  border-color: color-mix(in srgb, var(--zone-color, #64748b) 22%, #e5e7eb);
}

.stitch-stage--pixel .stitch-establishment-col {
  border-width: 2px;
  border-radius: 0;
  background: color-mix(in srgb, var(--zone-color, #64748b) 10%, #0f172a);
}

.stitch-stage--pixel .stitch-establishment-name {
  color: #f1f5f9;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 8px;
}

.stitch-stage--pixel .stitch-establishment-desc {
  color: #94a3b8;
  font-size: 8px;
}
</style>

