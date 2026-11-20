<template>
  <Trace v-if="rows.length" class="chat-turn-trace" data-testid="chat-turn-trace">
    <TraceCollapsible>
      <TraceCollapsibleTrigger class="chat-turn-trace__summary">
        <TraceLine>
          <TraceIcon><i class="fa fa-paperclip"></i></TraceIcon>
          <TraceTitle>附件读取</TraceTitle>
          <TraceDescription>{{ rows.length }} 次</TraceDescription>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <ul class="chat-turn-trace__list">
          <li v-for="(row, index) in rows" :key="`${row.tool}-${index}`" class="chat-turn-trace__item">
            <TraceCollapsible>
              <TraceCollapsibleTrigger class="chat-turn-trace__head">
                <TraceLine :status="row.ok ? undefined : 'error'" class="chat-turn-trace__line">
                  <TraceIcon><i class="fa" :class="row.ok ? 'fa-check-circle' : 'fa-times-circle'"></i></TraceIcon>
                  <TraceTitle>{{ row.title }}</TraceTitle>
                  <TraceDescription class="chat-turn-trace__ms">{{ row.ms }} ms</TraceDescription>
                  <span class="sr-only">{{ row.ok ? '已完成' : '失败' }}</span>
                </TraceLine>
              </TraceCollapsibleTrigger>
              <TraceCollapsibleContent>
                <div class="chat-turn-trace__detail">
                  <code>{{ row.tool }}</code>
                  <pre v-if="row.argsText" class="chat-turn-trace__args">{{ row.argsText }}</pre>
                  <p v-if="row.summary" class="chat-turn-trace__note">{{ row.summary }}</p>
                </div>
              </TraceCollapsibleContent>
            </TraceCollapsible>
          </li>
        </ul>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  </Trace>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChatTraceItem } from '@/composables/chat-orchestration/chatOrchestrationShared'
import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from '@/components/ui/trace'

const props = defineProps<{ items: ChatTraceItem[] }>()

/** 单个参数值最长展示 120 字，避免长文件路径/表格内容撑爆气泡。 */
const ARG_VALUE_LIMIT = 120
const ATTACHMENT_TOOL_LABELS: Record<string, string> = {
  list_attachments: '读取附件清单',
  describe_attachment: '查看文件结构',
  read_slice: '读取表格内容',
  read_text: '读取文件内容',
}

function truncateArgValues(value: unknown): unknown {
  if (typeof value === 'string') {
    return value.length > ARG_VALUE_LIMIT ? `${value.slice(0, ARG_VALUE_LIMIT)}…` : value
  }
  if (Array.isArray(value)) return value.map(truncateArgValues)
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, truncateArgValues(item)]))
  }
  return value
}

const rows = computed(() =>
  (props.items || []).map((item) => ({
    tool: item.tool,
    title: ATTACHMENT_TOOL_LABELS[item.tool] || item.tool,
    ok: item.ok !== false,
    ms: Number.isFinite(item.ms) ? item.ms : 0,
    argsText: item.args && Object.keys(item.args).length ? JSON.stringify(truncateArgValues(item.args), null, 2) : '',
    summary: String(item.summary || ''),
  })),
)
</script>

<style scoped>
.chat-turn-trace {
  margin: 6px 0;
}
.chat-turn-trace__summary,
.chat-turn-trace__head,
.chat-turn-trace__line {
  width: 100%;
}
.chat-turn-trace__summary {
  padding: 2px 0;
}
.chat-turn-trace__summary :deep(.xc-trace-chevron),
.chat-turn-trace__ms {
  margin-left: auto;
}
.chat-turn-trace__list {
  margin: 4px 0 0;
  padding: 0 0 0 12px;
  list-style: none;
}
.chat-turn-trace__item {
  padding: 3px 0;
}
.chat-turn-trace__detail {
  margin: 2px 0 6px 20px;
}
.chat-turn-trace__args {
  margin: 4px 0 0;
  max-height: 180px;
  overflow: auto;
  font:
    11px/1.5 ui-monospace,
    SFMono-Regular,
    Menlo,
    monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.chat-turn-trace__note {
  margin: 4px 0 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
