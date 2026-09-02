/**
 * 批量执行（Graph Run）面板。
 *
 * 由 DutyRosterGraphPanel.vue 模板机械切分而来（行为与视觉保持不变）。
 */
<script setup lang="ts">
import { computed } from 'vue'
import type { Deref } from './dutyRosterTypes'
import type { DutyRun } from './useDutyRun'
import type { DutyRosterState } from './useDutyRosterState'

const emit = defineEmits<{
  (e: 'update:runTargetId', v: Deref<DutyRosterState['runTargetId']>): void
  (e: 'update:runMaxConcurrency', v: Deref<DutyRosterState['runMaxConcurrency']>): void
  (e: 'update:runTaskBrief', v: Deref<DutyRosterState['runTaskBrief']>): void
  (e: 'update:runInputJson', v: Deref<DutyRosterState['runInputJson']>): void
  (e: 'update:runIncludeDependencies', v: Deref<DutyRosterState['runIncludeDependencies']>): void
  (e: 'update:runAllowHighRisk', v: Deref<DutyRosterState['runAllowHighRisk']>): void
}>()

const props = defineProps<{
  runTargetId: Deref<DutyRosterState['runTargetId']>
  runMaxConcurrency: Deref<DutyRosterState['runMaxConcurrency']>
  runTaskBrief: Deref<DutyRosterState['runTaskBrief']>
  runInputJson: Deref<DutyRosterState['runInputJson']>
  runIncludeDependencies: Deref<DutyRosterState['runIncludeDependencies']>
  runAllowHighRisk: Deref<DutyRosterState['runAllowHighRisk']>
  showRunPanel: Deref<DutyRosterState['showRunPanel']>
  runBusy: Deref<DutyRosterState['runBusy']>
  runError: Deref<DutyRosterState['runError']>
  latestRun: Deref<DutyRosterState['latestRun']>
  employees: Deref<DutyRosterState['employees']>
  startGraphRun: Deref<DutyRun['startGraphRun']>
}>()

const runTargetId = computed({
  get: () => props.runTargetId,
  set: (v) => emit('update:runTargetId', v),
})

const runMaxConcurrency = computed({
  get: () => props.runMaxConcurrency,
  set: (v) => emit('update:runMaxConcurrency', v),
})

const runTaskBrief = computed({
  get: () => props.runTaskBrief,
  set: (v) => emit('update:runTaskBrief', v),
})

const runInputJson = computed({
  get: () => props.runInputJson,
  set: (v) => emit('update:runInputJson', v),
})

const runIncludeDependencies = computed({
  get: () => props.runIncludeDependencies,
  set: (v) => emit('update:runIncludeDependencies', v),
})

const runAllowHighRisk = computed({
  get: () => props.runAllowHighRisk,
  set: (v) => emit('update:runAllowHighRisk', v),
})

</script>

<template>
            <transition name="dg-slide-top">
              <div v-if="showRunPanel" class="dg-run-panel">
                <div class="dg-run-grid">
                  <label class="dg-run-label">
                    <span>目标员工</span>
                    <select v-model="runTargetId" class="dg-run-select">
                      <option value="">请选择</option>
                      <option v-for="e in employees" :key="`run-${e.id}`" :value="e.id">
                        {{ e.name || e.id }} ({{ e.id }})
                      </option>
                    </select>
                  </label>
                  <label class="dg-run-label">
                    <span>并发上限</span>
                    <select v-model.number="runMaxConcurrency" class="dg-run-select">
                      <option :value="1">1</option>
                      <option :value="2">2</option>
                      <option :value="3">3</option>
                      <option :value="4">4</option>
                    </select>
                  </label>
                  <label class="dg-run-label dg-run-label--wide">
                    <span>任务 brief</span>
                    <textarea
                      v-model="runTaskBrief"
                      class="dg-run-textarea"
                      rows="2"
                      placeholder="例如：整理今日发布流程并输出执行摘要"
                    />
                  </label>
                  <label class="dg-run-label dg-run-label--wide">
                    <span>input_data JSON（对象）</span>
                    <textarea
                      v-model="runInputJson"
                      class="dg-run-textarea dg-run-textarea--mono"
                      rows="3"
                      placeholder='{"date":"2026-05-07","scope":"daily"}'
                    />
                  </label>
                </div>
                <div class="dg-run-options">
                  <label class="dg-run-check">
                    <input v-model="runIncludeDependencies" type="checkbox" />
                    <span>包含依赖上游</span>
                  </label>
                  <label class="dg-run-check">
                    <input v-model="runAllowHighRisk" type="checkbox" />
                    <span>允许高风险动作真实执行（管理员确认）</span>
                  </label>
                  <button
                    type="button"
                    class="dg-btn dg-btn--dispatch"
                    :disabled="runBusy || !runTaskBrief.trim() || !runTargetId"
                    @click="startGraphRun"
                  >
                    {{ runBusy ? '运行中…' : '开始运行' }}
                  </button>
                </div>
                <p v-if="runError" class="dg-run-error">{{ runError }}</p>
                <div v-if="latestRun" class="dg-run-summary">
                  <span class="dg-run-pill">#{{ latestRun.id }}</span>
                  <span class="dg-run-pill">状态 {{ latestRun.status }}</span>
                  <span class="dg-run-pill dg-run-pill--ok">成功 {{ latestRun.success_count }}</span>
                  <span class="dg-run-pill dg-run-pill--bad">失败 {{ latestRun.failed_count }}</span>
                  <span class="dg-run-pill dg-run-pill--warn">跳过 {{ latestRun.skipped_count }}</span>
                </div>
              </div>
            </transition>

            <!-- ── 全员汇报抽屉 ───────────────────────────────────────────── -->
</template>

<style scoped src="../DutyRosterGraphPanel.css"></style>
