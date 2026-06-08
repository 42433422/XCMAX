<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import MessageBody from '../MessageBody.vue'
import { stripInternalMarkers } from '../../../utils/lightMarkdown'
import { normalizeVoiceAsrText } from '../../../composables/normalizeVoiceAsrText'
import { foldDisplayVoiceMessages } from '../../../composables/voiceUserTurnCoalesce'

export interface VoiceFlowMessage {
  role: 'user' | 'assistant'
  content: string
}

const props = defineProps<{
  messages: VoiceFlowMessage[]
  streaming?: boolean
  liveText?: string
  isLiveNarrating?: boolean
  /** 正在说但未发送的用户语音 */
  liveUserText?: string
  micPaused?: boolean
  recognizing?: boolean
  speculating?: boolean
}>()

const flowRef = ref<HTMLElement | null>(null)
const bottomRef = ref<HTMLElement | null>(null)
let resizeObs: ResizeObserver | null = null

function cleanVoiceText(raw: string): string {
  return normalizeVoiceAsrText(
    stripInternalMarkers(String(raw || '')).replace(/\s+\n/g, '\n').trim(),
  )
}

const displayMessages = computed(() =>
  foldDisplayVoiceMessages(
    props.messages
      .map((m) => ({
        role: m.role,
        content: cleanVoiceText(m.content),
      }))
      .filter((m) => m.content && m.content !== '（无回复）') as Array<{
        role: 'user' | 'assistant'
        content: string
      }>,
  ),
)

const lastAssistantIdx = computed(() => {
  for (let i = displayMessages.value.length - 1; i >= 0; i--) {
    if (displayMessages.value[i]?.role === 'assistant') return i
  }
  return -1
})

const liveDisplay = computed(() => cleanVoiceText(props.liveText || ''))

const liveUserDisplay = computed(() => cleanVoiceText(props.liveUserText || ''))

const asrHintText = computed(() => {
  const n = liveUserDisplay.value.length
  if (n > 0 && n < 6) return '继续说，别急'
  return '听到了，等你说完'
})

const isEmpty = computed(
  () => !displayMessages.value.length && !showLiveLine.value && !liveUserDisplay.value,
)

const showLiveLine = computed(() => {
  if (!liveDisplay.value) return false
  const last = lastAssistantIdx.value >= 0 ? displayMessages.value[lastAssistantIdx.value]?.content : ''
  if (props.streaming || props.isLiveNarrating) {
    return !last || liveDisplay.value !== last
  }
  return false
})

function scrollToBottom(behavior: ScrollBehavior = 'smooth') {
  nextTick(() => {
    bottomRef.value?.scrollIntoView({ behavior, block: 'end' })
  })
}

watch(
  () => [
    displayMessages.value.length,
    displayMessages.value[displayMessages.value.length - 1]?.content,
    liveDisplay.value,
    liveUserDisplay.value,
    props.streaming,
  ],
  () => scrollToBottom(props.streaming ? 'auto' : 'smooth'),
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
  <div ref="flowRef" class="wb-voice-flow" aria-live="polite">
    <div class="wb-voice-flow__inner">
      <div v-if="isEmpty" class="wb-voice-flow__welcome">
        <p class="wb-voice-flow__welcome-title">像和人聊天一样说话就行</p>
        <p class="wb-voice-flow__welcome-sub">
          一句话、半个想法，或者一段需求都可以。我会接住上下文，先把你的意思聊顺，需要时再转任务或进制作流。
        </p>
        <p class="wb-voice-flow__welcome-hint">
          需要生成 Mod/员工时，请关闭顶部「平台模式」。
        </p>
        <div class="wb-voice-flow__starter-row" aria-hidden="true">
          <span>今天有点卡住</span>
          <span>帮我捋一下思路</span>
          <span>这句话怎么说自然</span>
        </div>
        <p v-if="micPaused" class="wb-voice-flow__welcome-paused">当前已暂停</p>
      </div>

      <article
        v-for="(m, i) in displayMessages"
        :key="`vf-${i}-${m.role}`"
        class="wb-voice-turn"
        :class="m.role === 'user' ? 'wb-voice-turn--user' : 'wb-voice-turn--assistant'"
      >
        <div v-if="m.role === 'user'" class="wb-voice-turn__user-col">
          <p class="wb-voice-turn__user">{{ m.content }}</p>
        </div>
        <div v-else class="wb-voice-turn__assistant-col">
          <div class="wb-voice-turn__assistant">
            <MessageBody
              :content="m.content"
              :streaming="streaming && i === lastAssistantIdx"
            />
          </div>
        </div>
      </article>

      <article v-if="liveUserDisplay" class="wb-voice-turn wb-voice-turn--user wb-voice-turn--live-user">
        <div class="wb-voice-turn__user-col">
          <p class="wb-voice-turn__user">
            {{ liveUserDisplay }}<span class="wb-voice-turn__cursor">▌</span>
          </p>
          <p v-if="recognizing && !speculating" class="wb-voice-turn__asr-hint">
            {{ asrHintText }}
          </p>
        </div>
      </article>

      <article v-if="speculating && !liveUserDisplay && !showLiveLine" class="wb-voice-turn wb-voice-turn--assistant wb-voice-turn--speculating">
        <div class="wb-voice-turn__assistant-col">
          <p class="wb-voice-turn__spec-hint">正在整理…</p>
        </div>
      </article>

      <article v-if="showLiveLine" class="wb-voice-turn wb-voice-turn--assistant wb-voice-turn--live">
        <div class="wb-voice-turn__assistant-col">
          <div class="wb-voice-turn__assistant">
            <MessageBody
              :content="liveDisplay"
              :streaming="isLiveNarrating || streaming"
            />
          </div>
        </div>
      </article>

      <div ref="bottomRef" class="wb-voice-flow__anchor" aria-hidden="true" />
    </div>
  </div>
</template>

<style scoped>
.wb-voice-flow {
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

.wb-voice-flow__inner {
  width: 100%;
  max-width: none;
  margin: 0;
  padding: 0.5rem clamp(0.75rem, 1.5vw, 1.25rem) 8.5rem;
  box-sizing: border-box;
}

.wb-voice-flow__welcome {
  padding: 2rem 0 2.5rem;
  text-align: left;
}

.wb-voice-flow__welcome-sub {
  margin: 0;
  font-size: 0.92rem;
  line-height: 1.65;
  color: rgba(255, 255, 255, 0.42);
  max-width: 520px;
}

.wb-voice-flow__welcome-hint {
  margin: 0.65rem 0 0;
  font-size: 0.84rem;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.32);
  max-width: 520px;
}

.wb-voice-flow__starter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 1rem;
  max-width: 520px;
}

.wb-voice-flow__starter-row span {
  display: inline-flex;
  align-items: center;
  min-height: 2rem;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.055);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.58);
  font-size: 0.82rem;
  line-height: 1.25;
}

.wb-voice-turn--live-user {
  opacity: 0.88;
}

.wb-voice-turn__asr-hint {
  margin: 0.15rem 0 0;
  font-size: 0.78rem;
  color: rgba(110, 231, 183, 0.75);
  text-align: right;
}

.wb-voice-turn--speculating {
  opacity: 0.92;
}

.wb-voice-turn__spec-hint {
  margin: 0;
  font-size: 0.92rem;
  color: rgba(129, 140, 248, 0.85);
  font-style: italic;
}

.wb-voice-turn__cursor {
  display: inline-block;
  margin-left: 2px;
  animation: wb-voice-cursor-blink 0.85s step-end infinite;
  opacity: 0.75;
}

.wb-voice-turn {
  padding: 0.85rem 0;
  animation: wb-voice-turn-in 0.28s ease-out both;
}

.wb-voice-turn--user {
  display: flex;
  justify-content: flex-end;
  width: 100%;
}

.wb-voice-turn__user-col {
  max-width: min(92%, 680px);
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.35rem;
  margin-left: auto;
}

.wb-voice-turn__user {
  margin: 0;
  font-size: 0.98rem;
  line-height: 1.7;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.9);
  white-space: pre-wrap;
  word-break: break-word;
  text-align: right;
}

.wb-voice-turn__assistant-col {
  width: 100%;
}

.wb-voice-turn__assistant {
  font-size: 1.05rem;
  line-height: 1.78;
  color: var(--wb-text-primary, #ececf1);
}

.wb-voice-turn__assistant :deep(.msg-body) {
  font-size: inherit;
  line-height: inherit;
  color: inherit;
}

.wb-voice-turn__assistant :deep(.msg-body p) {
  margin: 0 0 0.85rem;
}

.wb-voice-turn__assistant :deep(.msg-body p:last-child) {
  margin-bottom: 0;
}

.wb-voice-turn__assistant :deep(.msg-body__cursor) {
  display: inline-block;
  margin-left: 2px;
  animation: wb-voice-cursor-blink 0.85s step-end infinite;
  opacity: 0.8;
}

.wb-voice-flow__welcome-title {
  margin: 0 0 0.65rem;
  font-size: 1.35rem;
  font-weight: 650;
  letter-spacing: -0.02em;
  color: var(--wb-text-primary, #ececf1);
}

.wb-voice-flow__welcome-paused {
  margin: 1rem 0 0;
  font-size: 0.88rem;
  color: #fbbf24;
}

.wb-voice-flow__anchor {
  height: 1px;
  width: 100%;
  pointer-events: none;
}

@keyframes wb-voice-turn-in {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes wb-voice-cursor-blink {
  0%,
  100% {
    opacity: 0.15;
  }
  50% {
    opacity: 0.9;
  }
}

html[data-workbench-theme='light'] .wb-voice-turn__user {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-voice-turn__assistant {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-voice-flow__welcome-title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-voice-flow__welcome-sub {
  color: #86868b;
}

html[data-workbench-theme='light'] .wb-voice-flow__welcome-hint {
  color: #aeaeb2;
}

html[data-workbench-theme='light'] .wb-voice-flow__starter-row span {
  background: rgba(0, 0, 0, 0.04);
  border-color: rgba(0, 0, 0, 0.08);
  color: rgba(29, 29, 31, 0.62);
}

@media (max-width: 768px) {
  .wb-voice-flow__inner {
    padding: 0.35rem 0.65rem calc(12.5rem + 56px + env(safe-area-inset-bottom, 0px));
  }

  .wb-voice-flow__welcome {
    padding: 1.25rem 0 1.75rem;
  }

  .wb-voice-flow__welcome-title {
    font-size: 1.15rem;
  }

  .wb-voice-flow__welcome-sub {
    font-size: 0.88rem;
  }

  .wb-voice-turn__user-col {
    max-width: 92%;
  }

  .wb-voice-turn__user {
    font-size: 0.94rem;
  }

  .wb-voice-turn__assistant {
    font-size: 0.98rem;
    line-height: 1.72;
  }

  .wb-voice-turn__assistant :deep(.msg-body) {
    font-size: 0.98rem;
    line-height: 1.72;
    overflow-wrap: anywhere;
  }

  .wb-voice-turn__user {
    overflow-wrap: anywhere;
  }
}
</style>
