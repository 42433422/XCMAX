<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import type { EmployeeNodeData } from '../../../composables/useWorkbenchManifest'

const props = defineProps<{
  id: string
  data: EmployeeNodeData
  selected: boolean
}>()

const meta = computed(() => props.data.meta)

const summary = computed(() => {
  const s = props.data.slice as Record<string, unknown> | null | undefined
  if (!s) return '未配置'
  if (props.data.moduleKind === 'identity') {
    const id = s as Record<string, unknown>
    return String(id?.name || id?.id || '未命名')
  }
  if (props.data.moduleKind === 'prompt') {
    const agent = s as Record<string, unknown>
    const sp = String(agent?.system_prompt || '')
    return sp ? sp.slice(0, 60) + (sp.length > 60 ? '…' : '') : '未填写提示词'
  }
  if (props.data.moduleKind === 'skills') {
    const rawSlice: unknown = s
    const arr = Array.isArray(rawSlice) ? rawSlice : []
    return arr.length ? `${arr.length} 个技能` : '暂无技能'
  }
  if (props.data.moduleKind === 'workflow_heart') {
    const wf = s as Record<string, unknown>
    const wid = Number(wf?.workflow_id || 0)
    return wid > 0 ? `工作流 #${wid}` : '未绑定工作流'
  }
  if (props.data.moduleKind === 'memory') {
    const mem = s as Record<string, unknown>
    return mem?.long_term ? '短期 + 长期记忆' : '仅短期记忆'
  }
  return meta.value.label
})
</script>

<template>
  <div class="emp-node" :class="{ 'emp-node--selected': selected }" :style="{ '--accent': meta.accent }">
    <Handle type="target" :position="Position.Left" class="emp-handle emp-handle--in" />

    <header class="emp-node__head">
      <span class="emp-node__icon" :style="{ background: meta.accent }">{{ meta.icon }}</span>
      <div class="emp-node__titles">
        <span class="emp-node__type">{{ meta.required ? '必填' : '可选' }}</span>
        <span class="emp-node__label">{{ data.label }}</span>
      </div>
      <span v-if="!data.enabled" class="emp-node__badge emp-node__badge--off">已停用</span>
    </header>

    <p class="emp-node__summary">{{ summary }}</p>

    <Handle type="source" :position="Position.Right" class="emp-handle emp-handle--out" />
  </div>
</template>

<style scoped>
.emp-node {
  --accent: #6366f1;
  position: relative;
  width: 240px;
  min-height: 90px;
  background: rgba(15, 23, 42, 0.96);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-left: 3px solid var(--accent);
  border-radius: 14px;
  box-shadow:
    0 4px 6px -1px rgba(0, 0, 0, 0.4),
    inset 0 1px 0 rgba(255, 255, 255, 0.04);
  padding: 12px 14px 14px;
  cursor: grab;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  font-family: inherit;
}

.emp-node:hover {
  border-color: rgba(148, 163, 184, 0.2);
  transform: translateY(-2px);
  box-shadow:
    0 12px 24px -6px rgba(0, 0, 0, 0.5),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.emp-node--selected {
  border-color: var(--accent);
  box-shadow:
    0 0 0 2px color-mix(in srgb, var(--accent) 35%, transparent),
    0 12px 24px -6px rgba(0, 0, 0, 0.5);
}

.emp-node:active { cursor: grabbing; }

.emp-node__head {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 7px;
}

.emp-node__icon {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
  box-shadow: 0 0 14px color-mix(in srgb, var(--accent) 40%, transparent);
}

.emp-node__titles {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.emp-node__type {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--accent) 80%, #94a3b8);
  opacity: 0.75;
}

.emp-node__label {
  font-size: 14px;
  font-weight: 700;
  color: #f1f5f9;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.emp-node__badge {
  font-size: 9px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 999px;
  flex-shrink: 0;
}

.emp-node__badge--off {
  background: rgba(100, 116, 139, 0.2);
  color: #94a3b8;
  border: 1px solid rgba(100, 116, 139, 0.3);
}

.emp-node__summary {
  font-size: 11px;
  color: #94a3b8;
  margin: 0;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.emp-handle {
  width: 11px;
  height: 11px;
  background: var(--accent);
  border: 2px solid rgba(15, 23, 42, 0.96);
  border-radius: 50%;
  box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 50%, transparent);
  transition: transform 0.15s ease;
}

.emp-handle:hover { transform: scale(1.35); }
</style>
