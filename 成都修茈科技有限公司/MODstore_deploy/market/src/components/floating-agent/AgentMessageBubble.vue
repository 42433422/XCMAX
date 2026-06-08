<template>
  <article
    class="bubble-wrap"
    :class="[`bubble-wrap--${msg.role}`, { 'bubble-wrap--loading': msg.isLoading }]"
  >
    <div v-if="msg.role === 'user'" class="bubble bubble--user">
      {{ msg.content }}
    </div>

    <div v-else-if="msg.role === 'assistant'" class="bubble bubble--assistant">
      <template v-if="msg.isLoading">
        <span class="bubble-dots"><span /><span /><span /></span>
      </template>
      <template v-else>
        <!-- Simple markdown: convert \n to <br> and **bold** -->
        <!-- eslint-disable-next-line vue/no-v-html -->
        <span class="bubble-text" v-html="renderText(msg.content)" />
      </template>
    </div>

    <div v-else-if="msg.role === 'tool_call'" class="bubble bubble--tool">
      <span class="bubble-tool-icon">⚙️</span>
      <span>{{ msg.toolCall?.name || '工具调用' }}: {{ formatArgs(msg.toolCall?.args) }}</span>
    </div>

    <div v-else-if="msg.role === 'action_preview'" class="bubble bubble--preview">
      <div class="preview-header">
        <span class="preview-risk" :class="`preview-risk--${msg.actionPreview?.risk}`">
          {{ riskLabel(msg.actionPreview?.risk) }}
        </span>
        <span class="preview-label">{{ msg.actionPreview?.label }}</span>
      </div>
    </div>

    <time class="bubble-time">{{ formatTime(msg.timestamp) }}</time>
  </article>
</template>

<script setup lang="ts">
import type { AgentMessage } from '../../types/agent'

defineProps<{ msg: AgentMessage }>()

function renderText(content: string): string {
  return content
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

function formatArgs(args?: Record<string, unknown>): string {
  if (!args) return ''
  return Object.entries(args)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(', ')
}

function riskLabel(risk?: string): string {
  if (risk === 'high') return '高风险'
  if (risk === 'medium') return '中风险'
  return '低风险'
}

function formatTime(ts: number): string {
  const d = new Date(ts)
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}
</script>

<style scoped>
.bubble-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 10px;
}

.bubble-wrap--user { align-items: flex-end; }
.bubble-wrap--assistant,
.bubble-wrap--tool,
.bubble-wrap--action_preview { align-items: flex-start; }

.bubble {
  max-width: 88%;
  padding: 8px 11px;
  border-radius: 11px;
  font-size: 0.875rem;
  line-height: 1.5;
  word-break: break-word;
}

.bubble--user {
  background: rgba(59, 130, 246, 0.28);
  border: 1px solid rgba(96, 165, 250, 0.22);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.bubble--assistant {
  background: rgba(255, 255, 255, 0.045);
  border: 1px solid rgba(255, 255, 255, 0.075);
  color: rgba(255, 255, 255, 0.88);
  border-bottom-left-radius: 4px;
}

.bubble--tool {
  background: rgba(148, 163, 184, 0.08);
  border: 1px solid rgba(148, 163, 184, 0.16);
  color: #cbd5e1;
  font-size: 0.78rem;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
}

.bubble--preview {
  background: rgba(251, 191, 36, 0.08);
  border: 1px solid rgba(251, 191, 36, 0.25);
  color: #fde68a;
  padding: 8px 12px;
}

.preview-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.preview-risk {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 999px;
}

.preview-risk--high { background: rgba(248, 113, 113, 0.2); color: #f87171; }
.preview-risk--medium { background: rgba(251, 191, 36, 0.2); color: #fbbf24; }
.preview-risk--low { background: rgba(74, 222, 128, 0.2); color: #4ade80; }

.bubble-time {
  font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.25);
  padding: 0 4px;
}

.bubble-dots {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  height: 1em;
}

.bubble-dots span {
  display: inline-block;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.55);
  animation: dot-bounce 1.2s ease-in-out infinite;
}

.bubble-dots span:nth-child(2) { animation-delay: 0.2s; }
.bubble-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes dot-bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}

.bubble-text :deep(strong) { font-weight: 700; color: #fff; }
</style>
