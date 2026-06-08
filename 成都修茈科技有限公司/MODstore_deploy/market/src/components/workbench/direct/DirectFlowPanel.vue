<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import MessageBody from '../MessageBody.vue'
import MessageActions from '../MessageActions.vue'
import ThinkingRow from '../ThinkingRow.vue'
import type { ChatMessage } from '../../../utils/conversationStore'
import { formatDirectFileSize } from '../../../utils/directAttachments'

const props = defineProps<{
  messages: ChatMessage[]
  speakingMessageId?: string
}>()

const emit = defineEmits<{
  'download-output': [payload: { jobId: string; filename: string; label?: string }]
  regenerate: [messageId: string]
  speak: [messageId: string]
  feedback: [messageId: string, value: 'up' | 'down' | null]
  edit: [messageId: string]
}>()

const flowRef = ref<HTMLElement | null>(null)
const bottomRef = ref<HTMLElement | null>(null)
let resizeObs: ResizeObserver | null = null

const displayMessages = computed(() =>
  props.messages.filter((m) => m.role === 'user' || m.role === 'assistant'),
)

const lastAssistantIdx = computed(() => {
  for (let i = displayMessages.value.length - 1; i >= 0; i--) {
    if (displayMessages.value[i]?.role === 'assistant') return i
  }
  return -1
})

function scrollToBottom(behavior: ScrollBehavior = 'smooth') {
  nextTick(() => {
    bottomRef.value?.scrollIntoView({ behavior, block: 'end' })
  })
}

watch(
  () =>
    displayMessages.value
      .map((m) => `${m.id}:${m.content.length}:${m.pending ? 1 : 0}`)
      .join('|'),
  () => {
    const last = displayMessages.value[displayMessages.value.length - 1]
    scrollToBottom(last?.pending ? 'auto' : 'smooth')
  },
  { deep: true },
)

onMounted(() => {
  scrollToBottom('auto')
  if (typeof ResizeObserver !== 'undefined' && flowRef.value) {
    resizeObs = new ResizeObserver(() => scrollToBottom('auto'))
    resizeObs.observe(flowRef.value)
  }
})

onUnmounted(() => {
  resizeObs?.disconnect()
  resizeObs = null
})
</script>

<template>
  <div ref="flowRef" class="wb-direct-flow" aria-live="polite">
    <div class="wb-direct-flow__inner">
      <article
        v-for="(m, i) in displayMessages"
        :key="m.id"
        class="wb-direct-turn"
        :class="m.role === 'user' ? 'wb-direct-turn--user' : 'wb-direct-turn--assistant'"
      >
        <div v-if="m.role === 'user'" class="wb-direct-turn__user-col">
          <p v-if="m.attachments?.length" class="wb-direct-turn__meta">
            <span
              v-for="a in m.attachments"
              :key="`${m.id}-att-${a.name}`"
              class="wb-direct-turn__meta-item"
            >{{ a.name }} · {{ formatDirectFileSize(a.size) }}</span>
          </p>
          <p class="wb-direct-turn__user">{{ m.content }}</p>
          <MessageActions
            role="user"
            :content="m.content"
            @edit="emit('edit', m.id)"
          />
        </div>

        <div v-else class="wb-direct-turn__assistant-col">
          <div class="wb-direct-turn__assistant">
            <ThinkingRow v-if="m.pending && !String(m.content || '').trim()" />
            <MessageBody
              v-else
              :content="m.content"
              :streaming="!!m.pending && !!String(m.content || '').trim()"
            />
          </div>
          <MessageActions
            v-if="!m.pending"
            role="assistant"
            :content="m.content"
            :feedback="m.feedback"
            :can-regenerate="i === lastAssistantIdx"
            :speaking="speakingMessageId === m.id"
            @regenerate="emit('regenerate', m.id)"
            @speak="emit('speak', m.id)"
            @feedback="emit('feedback', m.id, $event)"
          />
          <p v-if="m.error" class="wb-direct-turn__err" role="alert">{{ m.error }}</p>
          <div v-if="m.outputDownloads?.length" class="wb-direct-turn__downloads">
            <button
              v-for="(dl, dli) in m.outputDownloads"
              :key="`dl-${m.id}-${dli}`"
              type="button"
              class="wb-direct-turn__dl"
              @click="emit('download-output', { jobId: dl.jobId, filename: dl.filename, label: dl.label })"
            >
              下载 {{ dl.label || dl.filename }}
            </button>
          </div>
          <div v-if="m.citations?.length" class="wb-direct-turn__cites">
            <details
              v-for="(cite, ci) in m.citations"
              :key="`cite-${m.id}-${ci}`"
              class="wb-direct-turn__cite"
            >
              <summary>{{ cite.title }}</summary>
              <p v-if="cite.snippet">{{ cite.snippet }}</p>
            </details>
          </div>
        </div>
      </article>

      <div ref="bottomRef" class="wb-direct-flow__anchor" aria-hidden="true" />
    </div>
  </div>
</template>

<style scoped>
.wb-direct-flow {
  flex: 1 1 0;
  min-height: 0;
  width: 100%;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scroll-behavior: smooth;
  scrollbar-width: thin;
  scrollbar-color: rgba(129, 140, 248, 0.15) transparent;
}

.wb-direct-flow__inner {
  width: 100%;
  max-width: none;
  margin: 0;
  padding: 0.5rem clamp(0.75rem, 1.5vw, 1.25rem) var(--wb-direct-footer-reserve, 6.5rem);
  box-sizing: border-box;
}

.wb-direct-turn {
  padding: 0.85rem 0;
  animation: wb-direct-turn-in 0.28s ease-out both;
}

.wb-direct-turn--user {
  display: flex;
  justify-content: flex-end;
  width: 100%;
}

.wb-direct-turn__user-col {
  max-width: min(92%, 680px);
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.35rem;
  margin-left: auto;
}

.wb-direct-turn__user-col:hover :deep(.msg-act),
.wb-direct-turn__user-col:focus-within :deep(.msg-act) {
  opacity: 1;
}

.wb-direct-turn__assistant-col:hover :deep(.msg-act),
.wb-direct-turn__assistant-col:focus-within :deep(.msg-act) {
  opacity: 1;
}

.wb-direct-turn__user {
  margin: 0;
  font-size: 0.98rem;
  line-height: 1.7;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.9);
  white-space: pre-wrap;
  word-break: break-word;
  text-align: right;
}

.wb-direct-turn__meta {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.35rem 0.65rem;
  font-size: 0.78rem;
  color: rgba(255, 255, 255, 0.38);
}

.wb-direct-turn__meta-item {
  white-space: nowrap;
}

.wb-direct-turn__assistant-col {
  width: 100%;
}

.wb-direct-turn__assistant {
  font-size: 1.05rem;
  line-height: 1.78;
  color: var(--wb-text-primary, #ececf1);
}

.wb-direct-turn__assistant :deep(.msg-body) {
  font-size: inherit;
  line-height: inherit;
  color: inherit;
}

.wb-direct-turn__assistant :deep(.msg-body p) {
  margin: 0 0 0.85rem;
}

.wb-direct-turn__assistant :deep(.msg-body p:last-child) {
  margin-bottom: 0;
}

.wb-direct-turn__err {
  margin: 0.65rem 0 0;
  font-size: 0.88rem;
  color: #fca5a5;
}

.wb-direct-turn__downloads {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.75rem;
}

.wb-direct-turn__dl {
  border: none;
  background: transparent;
  padding: 0;
  font: inherit;
  font-size: 0.88rem;
  color: #818cf8;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.wb-direct-turn__dl:hover {
  color: #a5b4fc;
}

.wb-direct-turn__cites {
  margin-top: 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.wb-direct-turn__cite {
  font-size: 0.82rem;
  color: rgba(255, 255, 255, 0.45);
}

.wb-direct-turn__cite summary {
  cursor: pointer;
  color: rgba(255, 255, 255, 0.55);
}

.wb-direct-turn__cite p {
  margin: 0.35rem 0 0;
  line-height: 1.55;
}

.wb-direct-flow__anchor {
  height: 1px;
  width: 100%;
  pointer-events: none;
}

@keyframes wb-direct-turn-in {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

html[data-workbench-theme='light'] .wb-direct-turn__user {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-direct-turn__meta {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-direct-turn__assistant {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-direct-turn__cite,
html[data-workbench-theme='light'] .wb-direct-turn__cite summary {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-direct-turn__dl {
  color: #0071e3;
}
</style>
