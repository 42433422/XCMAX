<template>
  <details v-if="rows.length" class="chat-turn-trace" data-testid="chat-turn-trace">
    <summary class="chat-turn-trace__summary">
      <span class="chat-turn-trace__title">本轮执行</span>
      <span class="chat-turn-trace__count">{{ rows.length }} 项</span>
      <i class="fa fa-angle-down chat-turn-trace__chevron" aria-hidden="true"></i>
    </summary>
    <ul class="chat-turn-trace__list">
      <li
        v-for="(row, index) in rows"
        :key="`${row.tool}-${index}`"
        class="chat-turn-trace__item"
        :class="row.ok ? 'is-ok' : 'is-fail'"
      >
        <div class="chat-turn-trace__head">
          <span class="chat-turn-trace__dot" :class="row.ok ? 'is-ok' : 'is-fail'" aria-hidden="true"></span>
          <span class="chat-turn-trace__tool">{{ row.tool }}</span>
          <span class="chat-turn-trace__ms">{{ row.ms }} ms</span>
        </div>
        <pre v-if="row.argsText" class="chat-turn-trace__args">{{ row.argsText }}</pre>
        <p v-if="row.summary" class="chat-turn-trace__note">{{ row.summary }}</p>
      </li>
    </ul>
  </details>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChatTraceItem } from '@/composables/chat-orchestration/chatOrchestrationShared'

const props = defineProps<{ items: ChatTraceItem[] }>()

/** 单个参数值最长展示 120 字，避免长文件路径/表格内容撑爆气泡。 */
const ARG_VALUE_LIMIT = 120

function truncateArgValues(value: unknown): unknown {
  if (typeof value === 'string') {
    return value.length > ARG_VALUE_LIMIT ? `${value.slice(0, ARG_VALUE_LIMIT)}…` : value
  }
  if (Array.isArray(value)) return value.map(truncateArgValues)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, truncateArgValues(item)]),
    )
  }
  return value
}

const rows = computed(() =>
  (props.items || []).map((item) => ({
    tool: item.tool,
    ok: item.ok !== false,
    ms: Number.isFinite(item.ms) ? item.ms : 0,
    argsText: item.args && Object.keys(item.args).length
      ? JSON.stringify(truncateArgValues(item.args), null, 2)
      : '',
    summary: String(item.summary || ''),
  })),
)
</script>

<style scoped>
.chat-turn-trace {
  margin: 6px 0;
  border: 1px solid var(--app-border-subtle, #e5e7eb);
  border-radius: 6px;
  font-size: var(--app-font-size-caption, 12px);
  color: var(--app-text-muted, #6b7280);
}

.chat-turn-trace__summary {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  cursor: pointer;
  list-style: none;
  user-select: none;
}

.chat-turn-trace__summary::-webkit-details-marker {
  display: none;
}

.chat-turn-trace[open] .chat-turn-trace__chevron {
  transform: rotate(180deg);
}

.chat-turn-trace__title {
  color: var(--app-text-primary, #333333);
}

.chat-turn-trace__chevron {
  margin-left: auto;
  transition: transform 0.15s ease;
}

.chat-turn-trace__list {
  margin: 0;
  padding: 0 8px 6px;
  list-style: none;
}

.chat-turn-trace__item + .chat-turn-trace__item {
  margin-top: 6px;
  border-top: 1px dashed var(--app-border-subtle, #e5e7eb);
  padding-top: 6px;
}

.chat-turn-trace__head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.chat-turn-trace__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #166534;
  flex: none;
}

.chat-turn-trace__dot.is-fail {
  background: #991b1b;
}

.chat-turn-trace__tool {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.chat-turn-trace__ms {
  margin-left: auto;
  opacity: 0.8;
}

.chat-turn-trace__args {
  margin: 4px 0 0;
  padding: 4px 6px;
  max-height: 180px;
  overflow: auto;
  border-radius: 4px;
  background: var(--app-surface-muted, rgba(255, 255, 255, 0.04));
  font-size: var(--app-font-size-caption, 12px);
  white-space: pre-wrap;
  word-break: break-all;
}

.chat-turn-trace__note {
  margin: 4px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
