<script setup lang="ts">
import { computed, ref } from 'vue'
import type { WorkflowFlowNode } from '../composables/useWorkflowGraph'

const props = defineProps<{
  nodes: WorkflowFlowNode[]
}>()

interface VarEntry {
  name: string
  source: string
  type: string
  value: string
}

const manualVars = ref<Record<string, string>>({})

const inferredVars = computed<VarEntry[]>(() => {
  const entries: VarEntry[] = []
  for (const node of props.nodes) {
    const config = node.data?.config || {}
    const outVar = (config as Record<string, unknown>).output_var
    if (typeof outVar === 'string' && outVar.trim()) {
      entries.push({
        name: outVar,
        source: node.data?.label || node.id,
        type: 'auto',
        value: '',
      })
    }
    const kind = node.data?.kind || ''
    if (kind === 'variable_set') {
      const vName = (config as Record<string, unknown>).name
      if (typeof vName === 'string' && vName.trim()) {
        entries.push({
          name: vName,
          source: node.data?.label || node.id,
          type: 'auto',
          value: String((config as Record<string, unknown>).value || ''),
        })
      }
    }
  }
  return entries
})

const allVars = computed<VarEntry[]>(() => {
  const auto = inferredVars.value
  const manual = Object.entries(manualVars.value).map(([name, value]) => ({
    name,
    source: '手动',
    type: 'manual',
    value,
  }))
  return [...auto, ...manual]
})

function addManualVar() {
  const key = `var_${Object.keys(manualVars.value).length + 1}`
  manualVars.value = { ...manualVars.value, [key]: '' }
}

function removeManualVar(name: string) {
  const next = { ...manualVars.value }
  delete next[name]
  manualVars.value = next
}

function updateManualVar(name: string, value: string) {
  manualVars.value = { ...manualVars.value, [name]: value }
}
</script>

<template>
  <div class="variables-panel">
    <div class="panel-header">
      <h3>变量</h3>
      <button class="btn-add" @click="addManualVar">+ 添加变量</button>
    </div>

    <div v-if="allVars.length === 0" class="empty-hint">
      暂无变量。添加节点或手动创建变量。
    </div>

    <div v-for="v in allVars" :key="v.name" class="var-row">
      <div class="var-name">
        <code v-text="'{{ ' + v.name + ' }}'"></code>
        <span class="var-badge" :class="v.type">{{ v.type === 'auto' ? '自动' : '手动' }}</span>
      </div>
      <div class="var-meta">
        <span class="var-source">来源: {{ v.source }}</span>
      </div>
      <div v-if="v.type === 'manual'" class="var-edit">
        <input
          :value="v.value"
          placeholder="默认值"
          @input="updateManualVar(v.name, ($event.target as HTMLInputElement).value)"
        />
        <button class="btn-remove" @click="removeManualVar(v.name)">✕</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.variables-panel {
  padding: 12px;
  font-size: 13px;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.panel-header h3 {
  margin: 0;
  font-size: 14px;
}
.btn-add {
  font-size: 12px;
  padding: 4px 10px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  background: #fff;
  cursor: pointer;
}
.btn-add:hover {
  background: #f3f4f6;
}
.empty-hint {
  color: #9ca3af;
  text-align: center;
  padding: 20px 0;
}
.var-row {
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 8px;
}
.var-name {
  display: flex;
  align-items: center;
  gap: 6px;
}
.var-name code {
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 12px;
}
.var-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
}
.var-badge.auto {
  background: #dbeafe;
  color: #1d4ed8;
}
.var-badge.manual {
  background: #fef3c7;
  color: #92400e;
}
.var-meta {
  margin-top: 4px;
  font-size: 11px;
  color: #6b7280;
}
.var-edit {
  display: flex;
  gap: 6px;
  margin-top: 6px;
}
.var-edit input {
  flex: 1;
  font-size: 12px;
  padding: 4px 8px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
}
.btn-remove {
  border: none;
  background: none;
  color: #ef4444;
  cursor: pointer;
  font-size: 14px;
}
</style>
