<template>
  <article class="bubble-wrap" :class="[`bubble-wrap--${msg.role}`, { 'bubble-wrap--loading': msg.isLoading }]">
    <div v-if="msg.role === 'user'" class="bubble bubble--user">
      {{ msg.content }}
    </div>

    <div v-else-if="msg.role === 'assistant'" class="bubble bubble--assistant" :class="{ 'bubble--error': msg.isError }" :role="msg.isError ? 'alert' : undefined">
      <template v-if="msg.isLoading">
        <span class="bubble-dots" role="status" aria-label="正在思考"><span aria-hidden="true" /><span aria-hidden="true" /><span aria-hidden="true" /></span>
      </template>
      <template v-else>
        <!-- Simple markdown: convert \n to <br> and **bold** -->
        <!-- eslint-disable-next-line vue/no-v-html -->
        <div class="bubble-text" v-html="renderText(msg.content)" />
      </template>
    </div>

    <div v-else-if="msg.role === 'tool_call'" class="bubble bubble--tool">
      <span class="bubble-tool-icon">⚙️</span>
      <span>{{ msg.toolCall?.name || '工具调用' }} · 参数已隐藏</span>
    </div>

    <div v-else-if="msg.role === 'action_preview'" class="bubble bubble--preview">
      <div class="preview-header">
        <span class="preview-risk" :class="`preview-risk--${msg.actionPreview?.risk}`">
          {{ riskLabel(msg.actionPreview?.risk) }}
        </span>
        <span class="preview-label">{{ msg.actionPreview?.label }}</span>
      </div>
    </div>

    <div v-if="(msg.role === 'user' || msg.role === 'assistant') && msg.content && !msg.isLoading" class="bubble-actions">
      <button type="button" class="bubble-copy" aria-label="复制消息正文" @click="copyMessage">复制</button>
      <span v-if="copyFeedback" role="status" class="bubble-copy-status">{{ copyFeedback }}</span>
    </div>
    <time class="bubble-time">{{ formatTime(msg.timestamp) }}</time>
  </article>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { AgentMessage } from '../../types/agent'
import { renderButlerBubbleHtml } from '../../utils/butlerBubbleText'

const props = defineProps<{ msg: AgentMessage }>()
const copyFeedback = ref('')

async function copyMessage() {
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable')
    await navigator.clipboard.writeText(props.msg.content)
    copyFeedback.value = '已复制'
  } catch {
    copyFeedback.value = '复制失败'
  }
}

function renderText(content: string): string {
  return renderButlerBubbleHtml(content)
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

.bubble-wrap--user {
  align-items: flex-end;
}
.bubble-wrap--assistant,
.bubble-wrap--tool,
.bubble-wrap--action_preview {
  align-items: flex-start;
}

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

.preview-risk--high {
  background: rgba(248, 113, 113, 0.2);
  color: #f87171;
}
.preview-risk--medium {
  background: rgba(251, 191, 36, 0.2);
  color: #fbbf24;
}
.preview-risk--low {
  background: rgba(74, 222, 128, 0.2);
  color: #4ade80;
}

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

.bubble-dots span:nth-child(2) {
  animation-delay: 0.2s;
}
.bubble-dots span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes dot-bounce {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-4px);
  }
}

.bubble-text :deep(strong) {
  font-weight: 700;
  color: #fff;
}

.bubble-text :deep(.bubble-link) {
  color: #60a5fa;
  text-decoration: underline;
  text-underline-offset: 2px;
  word-break: break-all;
}

.bubble-text :deep(.bubble-link:hover) {
  color: #93c5fd;
}

.bubble--error { border-color: rgba(248, 113, 113, .42); }
.bubble-actions { display: flex; align-items: center; gap: 8px; margin-top: 2px; }
.bubble-copy { background: transparent; border: 0; border-radius: 6px; color: inherit; opacity: .7; font-size: .72rem; padding: 4px 7px; cursor: pointer; }
.bubble-copy:hover, .bubble-copy:focus-visible { opacity: 1; background: rgba(148,163,184,.12); }
.bubble-copy:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
.bubble-copy-status { font-size: .72rem; }
.bubble-text :deep(.bubble-code) { margin: 6px 0; padding: 9px 11px; max-width: 100%; overflow-x: auto; white-space: pre; border-radius: 8px; background: rgba(15,23,42,.35); color: inherit; font: .83rem/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
@media (prefers-reduced-motion: reduce) { .bubble-dots span { animation: none; } }
</style>
