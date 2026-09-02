<script setup lang="ts">
// tutorial 模式图层（底图 + 工位叠层 + 热点）：由 StitchStage.vue 模板机械切分而来（行为保持不变）。
import type { YuangongStitchHotspot } from '@/constants/yuangongStitchHotspots'
import type { StitchEmployeePlacement } from '@/constants/yuangongStitchPlacements'
import type { WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'
import YuangongStation from '@/components/workflow/YuangongStation.vue'
import type { StitchComposedSlot } from './stitchStageTypes'

const props = defineProps<{
  imageSrc: string
  selectedEmpId: string | null
  hotspots: YuangongStitchHotspot[]
  placedStations: { placement: StitchEmployeePlacement; row: WorkflowEmployeeDeskRow }[]
  /** 父级登记底图元素（与原模板 ref="imgRef" 等价） */
  registerImgEl: (el: HTMLImageElement | null) => void
  hotspotLabel: (h: YuangongStitchHotspot) => string
  hotspotStyle: (h: YuangongStitchHotspot) => Record<string, string>
  placementStyle: (p: StitchEmployeePlacement) => Record<string, string>
  stationAriaLabel: (empId: string, row: StitchComposedSlot['row']) => string
  stationBusy: (row: StitchComposedSlot['row']) => boolean
}>()

const emit = defineEmits<{
  (e: 'select', empId: string): void
  (e: 'img-load'): void
  (e: 'image-error'): void
}>()

function setImgRef(el: unknown): void {
  props.registerImgEl(el as HTMLImageElement | null)
}
</script>

<template>
  <div class="stitch-stage-img-shell">
    <img
      :ref="setImgRef"
      class="stitch-stage-img"
      :src="imageSrc"
      alt=""
      decoding="async"
      draggable="false"
      @load="emit('img-load')"
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
        <YuangongStation :enabled="row.enabled" :busy="stationBusy(row)" :ariaLabel="stationAriaLabel(placement.empId, row)" />
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
</template>

<style scoped src="./stitch-stage.css"></style>
