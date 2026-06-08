<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../../../../api'
import { filterOutPlannedDutyEmployees } from '../../../../utils/workbenchEmployeeFilter'
import { getNodeMeta } from '../composables/useNodeRegistry'
import type { WorkflowFlowNode } from '../composables/useWorkflowGraph'

const props = defineProps<{
  selected: WorkflowFlowNode | null
}>()

const emit = defineEmits<{
  (e: 'patch', payload: { id: string; label?: string; config?: Record<string, unknown> }): void
  (e: 'delete', id: string): void
}>()

const employees = ref<Array<{ id: string; name?: string }>>([])
const employeesLoaded = ref(false)
const eskills = ref<Array<{ id: string | number; name?: string; domain?: string }>>([])
const eskillsLoaded = ref(false)

const meta = computed(() => (props.selected ? getNodeMeta(props.selected.data!.kind) : null))

const labelDraft = ref('')
const configDraft = ref<Record<string, unknown>>({})

watch(
  () => props.selected?.id,
  () => {
    if (props.selected) {
      labelDraft.value = props.selected.data!.label || ''
      configDraft.value = { ...(props.selected.data!.config || {}) }
    } else {
      labelDraft.value = ''
      configDraft.value = {}
    }
  },
  { immediate: true },
)

function commitLabel() {
  if (!props.selected) return
  emit('patch', { id: props.selected.id, label: labelDraft.value })
}

function setField(key: string, value: unknown) {
  configDraft.value = { ...configDraft.value, [key]: value }
  if (!props.selected) return
  emit('patch', { id: props.selected.id, config: configDraft.value })
}

async function ensureEmployees() {
  if (employeesLoaded.value) return
  try {
    const list: any = await api.listEmployees()
    const raw = Array.isArray(list) ? list : list?.employees || []
    employees.value = filterOutPlannedDutyEmployees(raw)
  } catch {
    employees.value = []
  } finally {
    employeesLoaded.value = true
  }
}

async function ensureESkills() {
  if (eskillsLoaded.value) return
  try {
    const list: any = await api.listESkills()
    eskills.value = Array.isArray(list) ? list : list?.eskills || []
  } catch {
    eskills.value = []
  } finally {
    eskillsLoaded.value = true
  }
}

onMounted(() => {
  void ensureEmployees()
  void ensureESkills()
})

function jsonToString(v: unknown): string {
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v ?? {}, null, 2)
  } catch {
    return ''
  }
}

function tryParseJson(raw: string): { ok: true; value: unknown } | { ok: false; error: string } {
  if (!raw.trim()) return { ok: true, value: {} }
  try {
    return { ok: true, value: JSON.parse(raw) }
  } catch (e) {
    return { ok: false, error: (e as Error).message }
  }
}

function onJsonInput(key: string, raw: string) {
  const r = tryParseJson(raw)
  if (r.ok) setField(key, r.value)
}

function onSwitchInput(key: string, ev: Event) {
  const target = ev.target as HTMLInputElement | null
  setField(key, !!target?.checked)
}

function onNumberInput(key: string, ev: Event) {
  const target = ev.target as HTMLInputElement | null
  const val = Number(target?.value || 0)
  setField(key, Number.isFinite(val) ? val : 0)
}

function eskillLabel(s: { id: string | number; name?: string; domain?: string }) {
  const name = s.name || String(s.id)
  return s.domain ? `${name} · ${s.domain}` : name
}
</script>

<template>
  <aside class="wf2-properties">
    <header class="wf2-properties__head">
      <h3 class="wf2-properties__title">属性</h3>
      <button v-if="selected" class="wf2-properties__del" type="button" @click="emit('delete', selected.id)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"/>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
        </svg>
        删除节点
      </button>
    </header>

    <div v-if="!selected" class="wf2-properties__empty">
      <svg class="wf2-properties__empty-icon" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
        <line x1="9" y1="9" x2="15" y2="15"/>
        <line x1="15" y1="9" x2="9" y2="15"/>
      </svg>
      <p>选中一个节点以编辑属性</p>
      <p class="wf2-properties__empty-sub">画布空白处单击可取消选中</p>
    </div>

    <div v-else class="wf2-properties__body">
      <div class="wf2-properties__meta">
        <span class="wf2-properties__chip" :style="{ '--accent': meta!.accent }">
          {{ meta!.label }}
        </span>
        <span class="wf2-properties__id">#{{ selected.data!.backendId || '新建' }}</span>
      </div>
      <p class="wf2-properties__desc">{{ meta!.description }}</p>

      <label class="wf2-field">
        <span class="wf2-field__label">名称</span>
        <input
          v-model="labelDraft"
          class="wf2-input"
          type="text"
          @blur="commitLabel"
          @keydown.enter.prevent="commitLabel"
        />
      </label>

      <template v-for="f in meta!.fields" :key="f.key">
        <label class="wf2-field">
          <span class="wf2-field__label">
            {{ f.label }}<span v-if="f.required" class="wf2-field__required">*</span>
          </span>

          <textarea
            v-if="f.type === 'textarea'"
            class="wf2-input wf2-input--ta"
            :value="String(configDraft[f.key] ?? '')"
            :placeholder="f.placeholder"
            rows="3"
            @input="setField(f.key, ($event.target as HTMLTextAreaElement).value)"
          />

          <input
            v-else-if="f.type === 'number'"
            class="wf2-input"
            type="number"
            :value="Number(configDraft[f.key] ?? 0)"
            :placeholder="f.placeholder"
            @input="onNumberInput(f.key, $event)"
          />

          <label v-else-if="f.type === 'switch'" class="wf2-switch">
            <input
              type="checkbox"
              :checked="Boolean(configDraft[f.key])"
              @change="onSwitchInput(f.key, $event)"
            />
            <span>{{ Boolean(configDraft[f.key]) ? '启用' : '关闭' }}</span>
          </label>

          <select
            v-else-if="f.type === 'select'"
            class="wf2-input"
            :value="String(configDraft[f.key] ?? '')"
            @change="setField(f.key, ($event.target as HTMLSelectElement).value)"
          >
            <option v-for="o in f.options || []" :key="String(o.value)" :value="String(o.value)">
              {{ o.label }}
            </option>
          </select>

          <select
            v-else-if="f.type === 'employee-picker'"
            class="wf2-input"
            :value="String(configDraft[f.key] ?? '')"
            @change="setField(f.key, ($event.target as HTMLSelectElement).value)"
          >
            <option value="">— 选择员工 —</option>
            <option v-for="e in employees" :key="String(e.id)" :value="String(e.id)">
              {{ e.name || e.id }}
            </option>
          </select>

          <select
            v-else-if="f.type === 'eskill-picker'"
            class="wf2-input"
            :value="String(configDraft[f.key] ?? '')"
            @change="setField(f.key, ($event.target as HTMLSelectElement).value)"
          >
            <option value="">— 选择 ESkill —</option>
            <option v-for="s in eskills" :key="String(s.id)" :value="String(s.id)">
              {{ eskillLabel(s) }}
            </option>
          </select>

          <textarea
            v-else-if="f.type === 'json'"
            class="wf2-input wf2-input--ta wf2-input--mono"
            :value="jsonToString(configDraft[f.key])"
            :placeholder="f.placeholder"
            rows="5"
            @input="onJsonInput(f.key, ($event.target as HTMLTextAreaElement).value)"
          />

          <input
            v-else
            class="wf2-input"
            type="text"
            :value="String(configDraft[f.key] ?? '')"
            :placeholder="f.placeholder"
            @input="setField(f.key, ($event.target as HTMLInputElement).value)"
          />

          <small v-if="f.helper" class="wf2-field__helper">{{ f.helper }}</small>
        </label>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.wf2-properties {
  width: 340px;
  flex-shrink: 0;
  border-left: 1px solid rgba(148, 163, 184, 0.08);
  background: rgba(15, 23, 42, 0.82);
  backdrop-filter: blur(16px);
  height: 100%;
  overflow-y: auto;
}

.wf2-properties__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 18px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
}

.wf2-properties__title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #f1f5f9;
}

.wf2-properties__del {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 500;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  color: #f87171;
  padding: 5px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.wf2-properties__del:hover {
  background: rgba(239, 68, 68, 0.2);
  border-color: rgba(239, 68, 68, 0.35);
}

.wf2-properties__empty {
  padding: 48px 20px;
  text-align: center;
  color: #64748b;
}

.wf2-properties__empty-icon {
  margin-bottom: 12px;
  color: #475569;
  opacity: 0.5;
}

.wf2-properties__empty-sub {
  font-size: 12px;
  color: #475569;
}

.wf2-properties__body {
  padding: 16px 18px 24px;
}

.wf2-properties__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.wf2-properties__chip {
  --accent: #6366f1;
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--accent) 18%, transparent);
  color: var(--accent);
  border: 1px solid color-mix(in srgb, var(--accent) 25%, transparent);
}

.wf2-properties__id {
  font-size: 11px;
  color: #475569;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.wf2-properties__desc {
  font-size: 12px;
  color: #64748b;
  margin: 4px 0 16px;
  line-height: 1.5;
}

.wf2-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}

.wf2-field__label {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 600;
}

.wf2-field__required {
  color: #f87171;
  margin-left: 2px;
}

.wf2-field__helper {
  font-size: 11px;
  color: #475569;
  line-height: 1.4;
}

.wf2-input {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  font-family: inherit;
  color: #f1f5f9;
  background: rgba(30, 41, 59, 0.6);
  transition: all 0.2s ease;
}

.wf2-input::placeholder {
  color: #475569;
}

.wf2-input:focus {
  outline: none;
  border-color: rgba(99, 102, 241, 0.5);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15);
  background: rgba(30, 41, 59, 0.8);
}

.wf2-input--ta {
  resize: vertical;
  line-height: 1.5;
}

.wf2-input--mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.wf2-switch {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: #cbd5e1;
}

.wf2-switch input[type="checkbox"] {
  width: 36px;
  height: 20px;
  appearance: none;
  background: rgba(148, 163, 184, 0.2);
  border-radius: 999px;
  position: relative;
  cursor: pointer;
  transition: background 0.2s ease;
}

.wf2-switch input[type="checkbox"]::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  background: #e2e8f0;
  border-radius: 50%;
  transition: transform 0.2s ease;
}

.wf2-switch input[type="checkbox"]:checked {
  background: rgba(99, 102, 241, 0.5);
}

.wf2-switch input[type="checkbox"]:checked::after {
  transform: translateX(16px);
  background: #fff;
}
</style>
