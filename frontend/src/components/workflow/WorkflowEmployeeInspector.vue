<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { useWorkflowEmployeeDesks, type WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'

const props = defineProps<{
  desks: WorkflowEmployeeDeskRow[]
  selectedEmpId: string | null
  /** 与全景页统一的像素风外观 */
  pixelSkin?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:selectedEmpId', value: string | null): void
}>()

const wfEmp = useWorkflowAiEmployeesStore()
const { statusLine, isBusy } = useWorkflowEmployeeDesks()

const listRef = ref<HTMLElement | null>(null)

function select(empId: string) {
  emit('update:selectedEmpId', empId === props.selectedEmpId ? null : empId)
}

watch(
  () => props.selectedEmpId,
  async (id) => {
    if (!id || !listRef.value) return
    await nextTick()
    const el = listRef.value.querySelector(`[data-emp-id="${id}"]`) as HTMLElement | null
    el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }
)

function progressWidth(row: WorkflowEmployeeDeskRow): string {
  if (!row.enabled) return '0%'
  const p = row.snapshot?.progressPct
  const n = typeof p === 'number' && Number.isFinite(p) ? Math.max(0, Math.min(100, p)) : 0
  return `${n}%`
}
</script>

<template>
  <aside
    class="wfe-inspector"
    :class="{ 'wfe-inspector--pixel': pixelSkin }"
    role="complementary"
    aria-label="工作流员工列表与开关"
  >
    <h3 class="wfe-inspector-h">员工与状态</h3>
    <p class="wfe-inspector-lead">
      开关与副窗「一键托管」一致；进度来自任务面板同步的快照。
    </p>

    <div ref="listRef" class="wfe-inspector-list" role="list">
      <div
        v-for="row in desks"
        :key="row.empId"
        class="wfe-inspector-row"
        :class="{ 'wfe-inspector-row--selected': selectedEmpId === row.empId }"
        :data-emp-id="row.empId"
        role="listitem"
      >
        <button
          type="button"
          class="wfe-inspector-hit"
          :aria-current="selectedEmpId === row.empId ? 'true' : undefined"
          @click="select(row.empId)"
        >
          <span class="wfe-inspector-name-row">
            <span class="wfe-inspector-short">{{ row.shortName }}</span>
            <span v-if="isBusy(row)" class="wfe-inspector-busy" aria-hidden="true">忙</span>
          </span>
          <span class="wfe-inspector-title" :title="row.panelTitle">{{ row.panelTitle }}</span>
          <span class="wfe-inspector-status">{{ statusLine(row) }}</span>
          <span class="wfe-inspector-progress-track" aria-hidden="true">
            <span class="wfe-inspector-progress-bar" :style="{ width: progressWidth(row) }" />
          </span>
        </button>

        <button
          type="button"
          class="wfe-inspector-toggle"
          :class="{ 'wfe-inspector-toggle--on': row.enabled }"
          :aria-pressed="row.enabled"
          :aria-label="(row.enabled ? '关闭' : '开启') + '副窗托管：' + row.shortName"
          @click="wfEmp.toggle(row.empId)"
        >
          {{ row.enabled ? '已开' : '已关' }}
        </button>
      </div>
    </div>

    <p class="wfe-inspector-foot">
      <router-link
        :to="{ name: 'workflow-employee-space', hash: '#ews-workflow-monitor' }"
        class="wfe-inspector-link"
      >
        在员工空间查看工位像素实况
      </router-link>
    </p>
  </aside>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap');

.wfe-inspector {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
  background: #fff;
  padding: 14px 14px 12px;
}

.wfe-inspector-h {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #111827;
}

.wfe-inspector-lead {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: #6b7280;
}

.wfe-inspector-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: min(52vh, 560px);
  overflow: auto;
  padding-right: 2px;
}

.wfe-inspector-row {
  display: flex;
  align-items: stretch;
  gap: 8px;
  border-radius: 10px;
  border: 1px solid #e5e7eb;
  background: #f9fafb;
  overflow: hidden;
}

.wfe-inspector-row--selected {
  border-color: #93c5fd;
  box-shadow: 0 0 0 1px #bfdbfe inset;
  background: #eff6ff;
}

.wfe-inspector-hit {
  flex: 1 1 auto;
  min-width: 0;
  padding: 10px 12px;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.wfe-inspector-hit:hover {
  background: rgba(255, 255, 255, 0.55);
}

.wfe-inspector-hit:focus {
  outline: none;
}

.wfe-inspector-hit:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: -2px;
}

.wfe-inspector-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.wfe-inspector-short {
  font-size: 14px;
  font-weight: 700;
  color: #111827;
}

.wfe-inspector-busy {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 999px;
  background: #dbeafe;
  color: #1d4ed8;
}

.wfe-inspector-title {
  font-size: 11px;
  line-height: 1.35;
  color: #6b7280;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.wfe-inspector-status {
  font-size: 12px;
  color: #374151;
}

.wfe-inspector-progress-track {
  width: 100%;
  height: 5px;
  border-radius: 999px;
  background: #e5e7eb;
  overflow: hidden;
  margin-top: 2px;
}

.wfe-inspector-progress-bar {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #60a5fa, #2563eb);
  min-width: 0;
  transition: width 0.2s ease;
}

.wfe-inspector-toggle {
  flex: 0 0 auto;
  align-self: stretch;
  min-width: 52px;
  padding: 0 10px;
  border: 0;
  border-left: 1px solid #e5e7eb;
  background: #fff;
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  cursor: pointer;
}

.wfe-inspector-toggle--on {
  color: #1d4ed8;
  background: #eff6ff;
}

.wfe-inspector-toggle:hover {
  filter: brightness(0.98);
}

.wfe-inspector-toggle:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: -2px;
  z-index: 1;
}

.wfe-inspector-foot {
  margin: 4px 0 0;
  font-size: 12px;
}

.wfe-inspector-link {
  color: #2563eb;
  text-decoration: none;
}

.wfe-inspector-link:hover {
  text-decoration: underline;
}

/* —— 全景页像素风（与舞台同一画框内） —— */
.wfe-inspector--pixel {
  border-radius: 0;
  border: none;
  background: #0b1020;
  padding: 10px 10px 12px;
  box-shadow: inset 0 0 0 2px #1e293b;
}

.wfe-inspector--pixel .wfe-inspector-h {
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 9px;
  line-height: 1.6;
  color: #f8fafc;
  letter-spacing: 0.04em;
}

.wfe-inspector--pixel .wfe-inspector-lead {
  font-size: 8px;
  line-height: 1.65;
  color: #94a3b8;
  font-family: ui-monospace, monospace;
}

.wfe-inspector--pixel .wfe-inspector-list {
  max-height: min(58vh, 640px);
}

.wfe-inspector--pixel .wfe-inspector-row {
  border-radius: 0;
  border: 3px solid #334155;
  background: #111827;
  box-shadow: inset 0 -2px 0 rgba(0, 0, 0, 0.35);
}

.wfe-inspector--pixel .wfe-inspector-row--selected {
  border-color: #38bdf8;
  box-shadow: inset 0 0 0 1px rgba(56, 189, 248, 0.35);
  background: #0f172a;
}

.wfe-inspector--pixel .wfe-inspector-hit:hover {
  background: rgba(56, 189, 248, 0.08);
}

.wfe-inspector--pixel .wfe-inspector-short {
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 8px;
  line-height: 1.5;
  color: #f1f5f9;
}

.wfe-inspector--pixel .wfe-inspector-busy {
  border-radius: 0;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 6px;
  padding: 4px 6px;
  background: #1e3a5f;
  color: #7dd3fc;
  border: 2px solid #38bdf8;
}

.wfe-inspector--pixel .wfe-inspector-title {
  font-size: 9px;
  color: #94a3b8;
}

.wfe-inspector--pixel .wfe-inspector-status {
  font-size: 10px;
  color: #cbd5e1;
}

.wfe-inspector--pixel .wfe-inspector-progress-track {
  height: 8px;
  border-radius: 0;
  background: #1e293b;
  border: 2px solid #334155;
}

.wfe-inspector--pixel .wfe-inspector-progress-bar {
  border-radius: 0;
  background: #22c55e;
  box-shadow: inset 0 -2px 0 rgba(0, 0, 0, 0.25);
}

.wfe-inspector--pixel .wfe-inspector-toggle {
  min-width: 56px;
  border-left: 3px solid #334155;
  background: #1e293b;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 7px;
  color: #cbd5e1;
}

.wfe-inspector--pixel .wfe-inspector-toggle--on {
  color: #4ade80;
  background: #14532d;
}

.wfe-inspector--pixel .wfe-inspector-foot {
  font-size: 8px;
}

.wfe-inspector--pixel .wfe-inspector-link {
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 7px;
  line-height: 1.7;
  color: #7dd3fc;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.wfe-inspector--pixel .wfe-inspector-hit:focus-visible {
  outline: 2px solid #facc15;
  outline-offset: -2px;
}

.wfe-inspector--pixel .wfe-inspector-toggle:focus-visible {
  outline: 2px solid #facc15;
}
</style>
