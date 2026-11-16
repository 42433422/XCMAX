/**
 * 缺岗分析面板。
 *
 * 由 DutyRosterGraphPanel.vue 模板机械切分而来（行为与视觉保持不变）。
 */
<script setup lang="ts">
import type { Deref } from './dutyRosterTypes'
import type { DutyGap } from './useDutyGap'
import type { DutyRosterState } from './useDutyRosterState'

defineEmits<{
}>()

defineProps<{
  showGapPanel: Deref<DutyRosterState['showGapPanel']>
  gapFocusHint: Deref<DutyRosterState['gapFocusHint']>
  gapRows: Deref<DutyGap['gapRows']>
  gapSummary: Deref<DutyGap['gapSummary']>
  focusEmployee: (id: string) => void
}>()

</script>

<template>
            <transition name="dg-slide-top">
              <div v-if="showGapPanel" class="dg-gap-panel">
                <p v-if="gapFocusHint" class="dg-gap-hint">{{ gapFocusHint }}</p>
                <details class="dg-gap-help"><summary>缺包、编制外与处理方式</summary></details>
                <div class="dg-gap-summary">
                  <span class="dg-gap-pill dg-gap-pill--deployed">包已对齐 {{ gapSummary.deployed }}</span>
                  <span class="dg-gap-pill dg-gap-pill--missing">包或目录缺口 {{ gapSummary.missing }}</span>
                  <span v-if="gapSummary.unknown" class="dg-gap-pill">待核实 {{ gapSummary.unknown }}</span>
                  <span v-if="gapSummary.untracked" class="dg-gap-pill dg-gap-pill--untracked">编制外包 {{ gapSummary.untracked }}</span>
                </div>
                <div class="dg-gap-list">
                  <div
                    v-for="row in gapRows"
                    :key="row.id"
                    class="dg-gap-row"
                    :class="`dg-gap-row--${row.state}`"
                    :title="row.id"
                    role="button" :tabindex="row.state === 'untracked' ? -1 : 0" :aria-disabled="row.state === 'untracked'"
                    @click="row.state !== 'untracked' && focusEmployee(row.id)"
                    @keydown.enter="row.state !== 'untracked' && focusEmployee(row.id)"
                  >
                    <span class="dg-gap-icon">{{ row.state === 'deployed' ? '✓' : row.state === 'missing' ? '✗' : '?' }}</span>
                    <span class="dg-gap-name">{{ row.name }}</span>
                    <span class="dg-gap-area">{{ row.area }}</span>
                    <small>{{ row.id }} · {{ row.detail }}</small>
                  </div>
                </div>
              </div>
            </transition>

</template>
