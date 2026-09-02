<script setup lang="ts">
// composed 模式舞台（企业编制列式 / 多排横拼）：由 StitchStage.vue 模板机械切分而来（行为保持不变）。
import YuangongStation from '@/components/workflow/YuangongStation.vue'
import { COMPOSED_LEFT_GROUP_SIZE, COMPOSED_ROW_GAP_PX, COMPOSED_SLOTS_PER_ROW } from './stitchStageConstants'
import type { StitchComposedSlot, StitchComposedRowGroups, StitchEstablishmentColumn } from './stitchStageTypes'

const props = defineProps<{
  selectedEmpId: string | null
  stripW: number
  outerHeightPx: number
  rowsAreaH: number
  labelFontPx: number
  showBackdrop: boolean
  backdropUrl: string
  empty: boolean
  idleDeskVisible: boolean
  isEstablishment: boolean
  establishmentColumns: StitchEstablishmentColumn[]
  establishmentColGap: number
  cellW: number
  trackH: number
  stationWrapStyle: { height: string }
  rows: StitchComposedSlot[][]
  midGapPx: number
  /** 父级登记根节点元素（与原模板 ref="composedRootRef" 等价） */
  registerRootEl: (el: HTMLElement | null) => void
  rowStripWidth: (cellCount: number) => number
  rowGroups: (rowSlots: StitchComposedSlot[]) => StitchComposedRowGroups
  cellOverlapMargin: (idx: number) => string
  stationAriaLabel: (empId: string, row: StitchComposedSlot['row']) => string
  stationBusy: (row: StitchComposedSlot['row']) => boolean
}>()

const emit = defineEmits<{
  (e: 'select', empId: string): void
  (e: 'backdrop-load'): void
  (e: 'backdrop-error'): void
}>()

function setComposedRootRef(el: unknown): void {
  props.registerRootEl(el as HTMLElement | null)
}
</script>

<template>
  <div
    :ref="setComposedRootRef"
    class="stitch-composed"
    :style="{
      width: `${stripW}px`,
      minHeight: `${outerHeightPx}px`,
      height: `${outerHeightPx}px`,
    }"
  >
    <div class="stitch-composed-strip" role="presentation">
      <div
        class="stitch-composed-scene"
        :style="{
          width: `${stripW}px`,
          height: `${rowsAreaH}px`,
          '--stitch-composed-label-font': `${labelFontPx}px`,
        }"
      >
        <img
          v-if="showBackdrop"
          :key="backdropUrl"
          class="stitch-composed-backdrop stitch-composed-backdrop--scene"
          :src="backdropUrl"
          alt=""
          decoding="async"
          draggable="false"
          @load="emit('backdrop-load')"
          @error="emit('backdrop-error')"
        />
        <p v-if="empty" class="stitch-composed-empty">暂无工作流员工；请从 MOD 商店安装工作流员工 Mod 后刷新。</p>
        <div
          v-else-if="isEstablishment"
          class="stitch-establishment"
          :style="{
            width: `${stripW}px`,
            height: `${rowsAreaH}px`,
            gap: `${establishmentColGap}px`,
          }"
        >
          <div
            v-for="col in establishmentColumns"
            :key="col.zone.id"
            class="stitch-establishment-col"
            :style="{
              width: `${cellW}px`,
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
                  width: `${cellW}px`,
                  height: `${trackH}px`,
                  marginTop: idx > 0 ? `${COMPOSED_ROW_GAP_PX}px` : '0',
                  zIndex: selectedEmpId === slot.empId ? 20 : idx + 1,
                }"
                @click.stop="emit('select', slot.empId)"
                @keydown.enter.prevent="emit('select', slot.empId)"
              >
                <div
                  class="stitch-composed-station-wrap"
                  :class="{
                    'stitch-composed-station-wrap--selected': selectedEmpId === slot.empId,
                  }"
                  :style="stationWrapStyle"
                >
                  <span class="stitch-composed-station-vis" aria-hidden="true">
                    <YuangongStation
                      pixel-layout="composed"
                      :composed-idle-desk-visible="idleDeskVisible"
                      :enabled="slot.row.enabled"
                      :busy="stationBusy(slot.row)"
                      :ariaLabel="stationAriaLabel(slot.empId, slot.row)"
                    />
                  </span>
                </div>
                <p class="stitch-composed-label" :title="slot.row.panelTitle">
                  {{ slot.row.shortName }}
                </p>
              </div>
            </div>
          </div>
        </div>
        <template v-else>
          <div
            v-for="(rowSlots, rowIdx) in rows"
            :key="'cmp-row-' + rowIdx"
            class="stitch-composed-row"
            :style="{
              width: `${rowStripWidth(rowSlots.length)}px`,
              height: `${trackH}px`,
              top: `${rowIdx * (trackH + COMPOSED_ROW_GAP_PX)}px`,
              left: `${(stripW - rowStripWidth(rowSlots.length)) / 2}px`,
            }"
          >
            <div class="stitch-composed-group">
              <div
                v-for="(slot, idx) in rowGroups(rowSlots).left"
                :key="'cmp-' + slot.empId"
                class="stitch-composed-cell"
                role="button"
                tabindex="0"
                :aria-label="stationAriaLabel(slot.empId, slot.row)"
                :aria-current="selectedEmpId === slot.empId ? 'true' : undefined"
                :style="{
                  width: `${cellW}px`,
                  height: `${trackH}px`,
                  marginLeft: cellOverlapMargin(idx),
                  zIndex: selectedEmpId === slot.empId ? 20 : rowIdx * COMPOSED_SLOTS_PER_ROW + idx + 1,
                }"
                @click.stop="emit('select', slot.empId)"
                @keydown.enter.prevent="emit('select', slot.empId)"
              >
                <div
                  class="stitch-composed-station-wrap"
                  :class="{
                    'stitch-composed-station-wrap--selected': selectedEmpId === slot.empId,
                  }"
                  :style="stationWrapStyle"
                >
                  <span class="stitch-composed-station-vis" aria-hidden="true">
                    <YuangongStation
                      pixel-layout="composed"
                      :composed-idle-desk-visible="idleDeskVisible"
                      :enabled="slot.row.enabled"
                      :busy="stationBusy(slot.row)"
                      :ariaLabel="stationAriaLabel(slot.empId, slot.row)"
                    />
                  </span>
                </div>
                <p class="stitch-composed-label" :title="slot.row.panelTitle">
                  {{ slot.row.shortName }}
                </p>
              </div>
            </div>
            <div
              v-if="rowGroups(rowSlots).right.length"
              class="stitch-composed-aisle"
              :style="{ width: `${midGapPx}px` }"
              aria-hidden="true"
            />
            <div v-if="rowGroups(rowSlots).right.length" class="stitch-composed-group">
              <div
                v-for="(slot, idx) in rowGroups(rowSlots).right"
                :key="'cmp-' + slot.empId"
                class="stitch-composed-cell"
                role="button"
                tabindex="0"
                :aria-label="stationAriaLabel(slot.empId, slot.row)"
                :aria-current="selectedEmpId === slot.empId ? 'true' : undefined"
                :style="{
                  width: `${cellW}px`,
                  height: `${trackH}px`,
                  marginLeft: cellOverlapMargin(idx),
                  zIndex: selectedEmpId === slot.empId ? 20 : rowIdx * COMPOSED_SLOTS_PER_ROW + COMPOSED_LEFT_GROUP_SIZE + idx + 1,
                }"
                @click.stop="emit('select', slot.empId)"
                @keydown.enter.prevent="emit('select', slot.empId)"
              >
                <div
                  class="stitch-composed-station-wrap"
                  :class="{
                    'stitch-composed-station-wrap--selected': selectedEmpId === slot.empId,
                  }"
                  :style="stationWrapStyle"
                >
                  <span class="stitch-composed-station-vis" aria-hidden="true">
                    <YuangongStation
                      pixel-layout="composed"
                      :composed-idle-desk-visible="idleDeskVisible"
                      :enabled="slot.row.enabled"
                      :busy="stationBusy(slot.row)"
                      :ariaLabel="stationAriaLabel(slot.empId, slot.row)"
                    />
                  </span>
                </div>
                <p class="stitch-composed-label" :title="slot.row.panelTitle">
                  {{ slot.row.shortName }}
                </p>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped src="./stitch-stage.css"></style>
