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
                <div class="dg-gap-summary">
                  <span class="dg-gap-pill dg-gap-pill--deployed">✓ 在岗 {{ gapSummary.deployed }}</span>
                  <span class="dg-gap-pill dg-gap-pill--missing">✗ 缺岗 {{ gapSummary.missing }}</span>
                  <span v-if="gapSummary.untracked" class="dg-gap-pill dg-gap-pill--untracked">? 游离 {{ gapSummary.untracked }}</span>
                </div>
                <div class="dg-gap-list">
                  <div
                    v-for="row in gapRows"
                    :key="row.id"
                    class="dg-gap-row"
                    :class="`dg-gap-row--${row.state}`"
                    :title="row.id"
                    @click="row.state !== 'missing' && focusEmployee(row.id)"
                  >
                    <span class="dg-gap-icon">{{ row.state === 'deployed' ? '✓' : row.state === 'missing' ? '✗' : '?' }}</span>
                    <span class="dg-gap-name">{{ row.name }}</span>
                    <span class="dg-gap-area">{{ row.area }}</span>
                  </div>
                </div>
              </div>
            </transition>

</template>

<style scoped src="../DutyRosterGraphPanel.css"></style>
