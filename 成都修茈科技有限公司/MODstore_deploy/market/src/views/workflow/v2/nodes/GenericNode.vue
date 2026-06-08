<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { getNodeMeta } from '../composables/useNodeRegistry'
import type { WorkflowFlowNodeData } from '../composables/useWorkflowGraph'

const props = defineProps<{
  id: string
  data: WorkflowFlowNodeData
  selected: boolean
}>()

const meta = computed(() => getNodeMeta(props.data.kind))

const summary = computed(() => {
  const cfg = props.data.config || {}
  const m = meta.value
  switch (m.kind) {
    case 'employee':
      return cfg.employee_id ? `员工 ${cfg.employee_id}` : '未选择员工'
    case 'eskill':
      return cfg.skill_id ? `ESkill ${cfg.skill_id}` : '未选择 ESkill'
    case 'condition':
      return cfg.expression ? String(cfg.expression).slice(0, 48) : '未配置表达式'
    case 'openapi_operation':
      return cfg.connector_id && cfg.operation_id
        ? `${cfg.connector_id}#${cfg.operation_id}`
        : '未配置连接器'
    case 'knowledge_search':
      return cfg.kb_id ? `KB ${cfg.kb_id}` : '未选择知识库'
    case 'webhook_trigger':
      return cfg.secret ? '含独立密钥' : '使用全局密钥'
    case 'cron_trigger':
      return cfg.cron ? String(cfg.cron) : '未设置 Cron'
    case 'variable_set':
      return cfg.name ? `${cfg.name} =` : '未设置变量'
    default:
      return m.description
  }
})
</script>

<template>
  <div
    class="wf2-node"
    :class="{ 'wf2-node--selected': selected }"
    :style="{ '--accent': meta.accent }"
  >
    <Handle
      v-if="meta.hasInput"
      type="target"
      :position="Position.Left"
      class="wf2-handle wf2-handle--in"
    />

    <header class="wf2-node__head">
      <span class="wf2-node__icon" :style="{ background: meta.accent }">{{ meta.icon }}</span>
      <div class="wf2-node__titles">
        <span class="wf2-node__type">{{ meta.label }}</span>
        <span class="wf2-node__name" :title="data.label">{{ data.label }}</span>
      </div>
    </header>

    <p class="wf2-node__summary" :title="String(summary)">{{ summary }}</p>

    <template v-if="meta.branchOutputs">
      <Handle
        type="source"
        :position="Position.Right"
        id="true"
        class="wf2-handle wf2-handle--out wf2-handle--true"
      />
      <Handle
        type="source"
        :position="Position.Right"
        id="false"
        class="wf2-handle wf2-handle--out wf2-handle--false"
      />
      <span class="wf2-branch-label wf2-branch-label--true">true</span>
      <span class="wf2-branch-label wf2-branch-label--false">false</span>
    </template>
    <Handle
      v-else-if="meta.hasOutput"
      type="source"
      :position="Position.Right"
      class="wf2-handle wf2-handle--out"
    />
  </div>
</template>

<style scoped>
.wf2-node {
  --accent: #6366f1;
  position: relative;
  width: 240px;
  min-height: 100px;
  background: rgba(30, 41, 59, 0.95);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-left: 3px solid var(--accent);
  border-radius: 14px;
  box-shadow:
    0 4px 6px -1px rgba(0, 0, 0, 0.3),
    0 2px 4px -2px rgba(0, 0, 0, 0.2),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
  padding: 14px 16px 16px;
  font-family: inherit;
  cursor: grab;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.wf2-node:hover {
  box-shadow:
    0 20px 25px -5px rgba(0, 0, 0, 0.4),
    0 8px 10px -6px rgba(0, 0, 0, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
  border-color: rgba(148, 163, 184, 0.22);
  transform: translateY(-2px);
}

.wf2-node--selected {
  border-color: var(--accent);
  box-shadow:
    0 0 0 2px color-mix(in srgb, var(--accent) 40%, transparent),
    0 20px 25px -5px rgba(0, 0, 0, 0.4),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.wf2-node:active {
  cursor: grabbing;
}

.wf2-node__head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.wf2-node__icon {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 15px;
  flex-shrink: 0;
  box-shadow: 0 0 16px color-mix(in srgb, var(--accent) 35%, transparent);
}

.wf2-node__titles {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.wf2-node__type {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: rgba(148, 163, 184, 0.7);
  text-transform: uppercase;
}

.wf2-node__name {
  font-size: 14px;
  font-weight: 700;
  color: #f1f5f9;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.wf2-node__summary {
  font-size: 12px;
  color: #94a3b8;
  margin: 0;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.wf2-handle {
  width: 12px;
  height: 12px;
  background: var(--accent);
  border: 2px solid rgba(30, 41, 59, 0.95);
  border-radius: 50%;
  box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 50%, transparent);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.wf2-handle:hover {
  transform: scale(1.3);
}

.wf2-handle--true {
  top: 38%;
  background: #22c55e;
  box-shadow: 0 0 8px rgba(34, 197, 94, 0.5);
}

.wf2-handle--false {
  top: 72%;
  background: #ef4444;
  box-shadow: 0 0 8px rgba(239, 68, 68, 0.5);
}

.wf2-branch-label {
  position: absolute;
  right: -46px;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  pointer-events: none;
  letter-spacing: 0.02em;
}

.wf2-branch-label--true {
  top: calc(38% - 8px);
  background: rgba(34, 197, 94, 0.18);
  color: #4ade80;
  border: 1px solid rgba(34, 197, 94, 0.25);
}

.wf2-branch-label--false {
  top: calc(72% - 8px);
  background: rgba(239, 68, 68, 0.18);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.25);
}
</style>
