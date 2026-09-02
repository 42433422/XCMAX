<script setup lang="ts">
// 入口 façade：逻辑拆至 ./stitch-stage/ 下的 composables 与子组件，对外 props/行为不变。
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { YuangongStitchHotspot } from '@/constants/yuangongStitchHotspots'
import type { StitchEmployeePlacement } from '@/constants/yuangongStitchPlacements'
import { YUANGONG_ENTRY_STITCH_PNG } from '@/constants/yuangongAssets'
import type { WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'
import { useStitchComposedLayout } from './stitch-stage/useStitchComposedLayout'
import { useStitchPanZoom } from './stitch-stage/useStitchPanZoom'
import type { StitchStageProps } from './stitch-stage/stitchStageTypes'
import { maxZoom, minZoom, zoomStep } from './stitch-stage/stitchStageConstants'
import StitchStageToolbar from './stitch-stage/StitchStageToolbar.vue'
import StitchComposedStage from './stitch-stage/StitchComposedStage.vue'
import StitchTutorialLayer from './stitch-stage/StitchTutorialLayer.vue'

const props = withDefaults(defineProps<StitchStageProps>(), {
  mode: 'tutorial',
  desks: () => [],
  stationPlacements: () => [],
  useComposedPanorama: true,
  visualSkin: 'pixel',
  composedLayout: 'strip',
})

const emit = defineEmits<{
  (e: 'select', empId: string): void
  (e: 'image-error'): void
}>()

const viewportRef = ref<HTMLElement | null>(null)
const imgRef = ref<HTMLImageElement | null>(null)
const composedRootRef = ref<HTMLElement | null>(null)

/** 子组件经函数 ref 登记 DOM 元素（与原模板字符串 ref 等价，含卸载时回填 null） */
function registerTutorialImgEl(el: HTMLImageElement | null): void {
  imgRef.value = el
}

function registerComposedRootEl(el: HTMLElement | null): void {
  composedRootRef.value = el
}

const isComposed = computed(() => props.mode === 'composed')

const layout = useStitchComposedLayout(props, viewportRef)
const {
  deskW,
  deskH,
  deskIntrinsicReady,
  isEstablishmentLayout,
  composedStationScale,
  composedCellW,
  composedMidGapPx,
  composedEstablishmentColGap,
  composedLabelFontPx,
  composedTrackH,
  composedGroupStripWidth,
  composedRowGroups,
  composedCellOverlapMargin,
  composedRowStripWidth,
  composedSlots,
  composedRows,
  establishmentColumns,
  composedStripW,
  composedRowsAreaH,
  composedOuterHeightPx,
  composedStationWrapStyle,
  updateViewportSize,
} = layout

const {
  zoom,
  middlePanning,
  zoomPct,
  zoomLayerStyle,
  onViewportPointerDown,
  onViewportPointerMove,
  onViewportPointerUp,
  onViewportPointerCancel,
  onViewportMouseDown,
  onViewportAuxClick,
  scheduleFit,
  clampPan,
  zoomIn,
  zoomOut,
  resetZoom,
  onZoomInput,
} = useStitchPanZoom(props, { viewportRef, imgRef, composedRootRef, composedOuterHeightPx })

type ComposedBackdropState = 'idle' | 'ready' | 'error'
const composedBackdropState = ref<ComposedBackdropState>('idle')

const composedPanoramaUrl = computed(() => {
  if (props.mode !== 'composed' || props.useComposedPanorama === false) return ''
  const trimmed = (props.imageSrc || '').trim()
  return trimmed || YUANGONG_ENTRY_STITCH_PNG
})

const showComposedBackdrop = computed(() => isComposed.value && Boolean(composedPanoramaUrl.value))

/** 全景底图加载成功后，空闲格不再叠整张 desk，避免与底图「双工位」 */
const composedIdleDeskVisible = computed(() => !showComposedBackdrop.value || composedBackdropState.value !== 'ready')

watch(composedPanoramaUrl, () => {
  composedBackdropState.value = 'idle'
})

watch(
  () => props.mode,
  (m) => {
    if (m !== 'composed') composedBackdropState.value = 'idle'
  },
)

function onComposedBackdropLoad() {
  composedBackdropState.value = 'ready'
  void nextTick(() => scheduleFit())
}

function onComposedBackdropError() {
  composedBackdropState.value = 'error'
  emit('image-error')
}

function onImgLoad() {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => scheduleFit())
  })
}

let viewportResizeObserver: ResizeObserver | null = null

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

const placedStations = computed(() => {
  const list: { placement: StitchEmployeePlacement; row: WorkflowEmployeeDeskRow }[] = []
  for (const placement of props.stationPlacements) {
    const row = props.desks.find((d) => d.empId === placement.empId)
    if (row) list.push({ placement, row })
  }
  return list
})

function stationBusy(row: WorkflowEmployeeDeskRow): boolean {
  if (!row.enabled) return false
  return row.snapshot?.visuallyBusy === true
}

function stationAriaLabel(empId: string, row: WorkflowEmployeeDeskRow): string {
  if (props.resolveStationAriaLabel) return props.resolveStationAriaLabel(empId)
  return `员工 ${row.shortName}`
}

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

function placementStyle(p: StitchEmployeePlacement) {
  const s = p.scale ?? 4
  return {
    left: `${p.leftPct}%`,
    top: `${p.topPct}%`,
    transform: `translate(-50%, -100%) scale(${s})`,
    transformOrigin: '50% 100%',
  }
}

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
  },
)

watch(
  () => props.mode,
  () => {
    void nextTick(() => scheduleFit())
  },
)

watch(
  () => props.desks.map((d) => d.empId).join('\0'),
  () => {
    if (props.mode === 'composed') {
      void nextTick(() => scheduleFit())
    }
  },
)

watch(
  () => props.desks.map((d) => `${d.empId}:${d.enabled}:${d.snapshot?.visuallyBusy}`).join('|'),
  () => {
    if (props.mode === 'composed') {
      void nextTick(() => clampPan())
    }
  },
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
  },
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
    <StitchStageToolbar
      :zoom="zoom"
      :min-zoom="minZoom"
      :max-zoom="maxZoom"
      :zoom-step="zoomStep"
      :zoom-pct="zoomPct"
      @zoom-in="zoomIn"
      @zoom-out="zoomOut"
      @reset="resetZoom"
      @zoom-input="onZoomInput"
    />

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
        <StitchComposedStage
          v-if="isComposed"
          :selected-emp-id="props.selectedEmpId"
          :strip-w="composedStripW"
          :outer-height-px="composedOuterHeightPx"
          :rows-area-h="composedRowsAreaH"
          :label-font-px="composedLabelFontPx"
          :show-backdrop="showComposedBackdrop"
          :backdrop-url="composedPanoramaUrl"
          :empty="composedSlots.length === 0"
          :idle-desk-visible="composedIdleDeskVisible"
          :is-establishment="isEstablishmentLayout"
          :establishment-columns="establishmentColumns"
          :establishment-col-gap="composedEstablishmentColGap"
          :cell-w="composedCellW"
          :track-h="composedTrackH"
          :station-wrap-style="composedStationWrapStyle"
          :rows="composedRows"
          :mid-gap-px="composedMidGapPx"
          :register-root-el="registerComposedRootEl"
          :row-strip-width="composedRowStripWidth"
          :row-groups="composedRowGroups"
          :cell-overlap-margin="composedCellOverlapMargin"
          :station-aria-label="stationAriaLabel"
          :station-busy="stationBusy"
          @select="emit('select', $event)"
          @backdrop-load="onComposedBackdropLoad"
          @backdrop-error="onComposedBackdropError"
        />
        <StitchTutorialLayer
          v-else
          :image-src="props.imageSrc"
          :selected-emp-id="props.selectedEmpId"
          :hotspots="props.hotspots"
          :placed-stations="placedStations"
          :register-img-el="registerTutorialImgEl"
          :hotspot-label="hotspotLabel"
          :hotspot-style="hotspotStyle"
          :placement-style="placementStyle"
          :station-aria-label="stationAriaLabel"
          :station-busy="stationBusy"
          @select="emit('select', $event)"
          @img-load="onImgLoad"
          @image-error="emit('image-error')"
        />
      </div>
    </div>
  </div>
</template>

<style scoped src="./stitch-stage/stitch-stage.css"></style>
