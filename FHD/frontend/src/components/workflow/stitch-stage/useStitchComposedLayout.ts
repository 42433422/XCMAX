/**
 * composed 模式布局：单格缩放、行列编排与 establishment 列式工位图。
 * 由 StitchStage.vue 原文机械切分而来（行为保持不变）。
 */
import { computed, ref } from 'vue'
import type { Ref } from 'vue'
import { YUANGONG_CANVAS_H, YUANGONG_CANVAS_W, yuangongComposedBaseSizeFromCanvas } from '@/constants/yuangongComposedTrim'
import { useYuangongDeskIntrinsicSize } from '@/composables/useYuangongDeskIntrinsicSize'
import {
  ENTERPRISE_ORG_LAYERS,
  countEnterpriseEstablishmentMaxSlots,
  resolveEnterpriseOrgLayer,
} from '@/constants/enterpriseWorkflowEstablishment'
import {
  COMPOSED_DESK_LAYOUT_MAX_DIM,
  COMPOSED_FIT_PAD,
  COMPOSED_LEFT_GROUP_SIZE,
  COMPOSED_MID_GAP_MIN_PX,
  COMPOSED_MID_GAP_RATIO,
  COMPOSED_MIN_STATION_H_PX,
  COMPOSED_OUTER_WIDTH_EXTRA,
  COMPOSED_ROW_GAP_PX,
  COMPOSED_ROOT_VERTICAL_CHROME,
  COMPOSED_SCALE_FALLBACK,
  COMPOSED_SCALE_MAX,
  COMPOSED_SCALE_MIN,
  COMPOSED_SLOTS_PER_ROW,
  COMPOSED_TARGET_HEIGHT_RATIO,
  COMPOSED_TARGET_SHRINK,
} from './stitchStageConstants'
import type { StitchComposedSlot, StitchEstablishmentColumn, StitchStageProps } from './stitchStageTypes'

export function useStitchComposedLayout(props: StitchStageProps, viewportRef: Ref<HTMLElement | null>) {
  /** desk.png 实际像素（naturalWidth/Height）；未加载前为默认 80×58 */
  const { deskW, deskH, deskIntrinsicReady } = useYuangongDeskIntrinsicSize()

  const composedLayoutDeskW = computed(() =>
    deskW.value > COMPOSED_DESK_LAYOUT_MAX_DIM || deskH.value > COMPOSED_DESK_LAYOUT_MAX_DIM ? YUANGONG_CANVAS_W : deskW.value,
  )
  const composedLayoutDeskH = computed(() =>
    deskW.value > COMPOSED_DESK_LAYOUT_MAX_DIM || deskH.value > COMPOSED_DESK_LAYOUT_MAX_DIM ? YUANGONG_CANVAS_H : deskH.value,
  )

  /** 舞台视口宽高（ResizeObserver），用于 composed 动态缩放 */
  const viewportW = ref(0)
  const viewportH = ref(0)

  const composedBaseSize = computed(() => yuangongComposedBaseSizeFromCanvas(composedLayoutDeskW.value, composedLayoutDeskH.value))
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
        const maxSlots = countEnterpriseEstablishmentMaxSlots(props.desks ?? [])
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

    const rowCount = Math.max(1, Math.ceil((props.desks ?? []).length / COMPOSED_SLOTS_PER_ROW))
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
  const composedCellOverlapPx = computed(() => Math.max(10, Math.round(composedCellW.value * 0.44)))

  const composedMidGapPx = computed(() => Math.max(COMPOSED_MID_GAP_MIN_PX, Math.round(composedCellW.value * COMPOSED_MID_GAP_RATIO)))

  const isEstablishmentLayout = computed(() => props.mode === 'composed' && props.composedLayout === 'establishment')

  const composedEstablishmentColGap = computed(() => Math.max(12, Math.round(composedCellW.value * 0.1)))

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

  function composedGroupStripWidth(count: number): number {
    if (count <= 0) return 0
    const cw = composedCellW.value
    const overlap = composedCellOverlapPx.value
    return cw * count - (count - 1) * overlap
  }

  function composedRowGroups(rowSlots: StitchComposedSlot[]) {
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

  const composedSlots = computed<StitchComposedSlot[]>(() => (props.desks ?? []).map((row) => ({ empId: row.empId, row })))

  const composedRows = computed<StitchComposedSlot[][]>(() => {
    const slots = composedSlots.value
    const rows: StitchComposedSlot[][] = []
    for (let i = 0; i < slots.length; i += COMPOSED_SLOTS_PER_ROW) {
      rows.push(slots.slice(i, i + COMPOSED_SLOTS_PER_ROW))
    }
    return rows
  })

  const establishmentColumns = computed<StitchEstablishmentColumn[]>(() => {
    const slots = composedSlots.value
    const byZone = new Map<string, StitchComposedSlot[]>()
    for (const z of ENTERPRISE_ORG_LAYERS) {
      byZone.set(z.id, [])
    }
    for (const slot of slots) {
      const zid = resolveEnterpriseOrgLayer(slot.empId, slot.row.shortName, slot.row.panelTitle)
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
    return countEnterpriseEstablishmentMaxSlots(props.desks ?? [])
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

  function updateViewportSize(): void {
    const el = viewportRef.value
    if (el) {
      viewportW.value = el.clientWidth
      viewportH.value = el.clientHeight
    }
  }

  return {
    deskW,
    deskH,
    deskIntrinsicReady,
    viewportW,
    viewportH,
    updateViewportSize,
    composedBaseW,
    composedBaseH,
    composedStationScale,
    composedCellW,
    composedCellOverlapPx,
    composedMidGapPx,
    isEstablishmentLayout,
    composedEstablishmentColGap,
    composedStationH,
    composedLabelBandH,
    composedLabelFontPx,
    composedTrackH,
    composedGroupStripWidth,
    composedRowGroups,
    composedCellOverlapMargin,
    composedRowStripWidth,
    composedSlots,
    composedRows,
    establishmentColumns,
    establishmentMaxSlots,
    composedStripW,
    composedRowsAreaH,
    composedOuterHeightPx,
    composedStationWrapStyle,
  }
}

export type StitchComposedLayout = ReturnType<typeof useStitchComposedLayout>
