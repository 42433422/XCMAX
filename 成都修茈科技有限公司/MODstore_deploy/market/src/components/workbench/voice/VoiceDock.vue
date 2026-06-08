<script setup lang="ts">
import { computed, ref } from 'vue'
import { scrollInputIntoViewOnMobile } from '../../../composables/voiceDevice'

const props = defineProps<{
  micPaused: boolean
  connecting?: boolean
  connectingHint?: string
  recognizing?: boolean
  listening: boolean
  micLive?: boolean
  chatBusy: boolean
  speculating?: boolean
  hasAssistantContent?: boolean
  voiceState: string
  ttsActive: boolean
  asrBackendLabel?: string
  draft: string
  workPhase?: string
}>()

const emit = defineEmits<{
  'toggle-mic': []
  send: []
  'update:draft': [value: string]
}>()

const micTitle = computed(() => {
  if (props.micPaused) return '继续对话'
  if (props.connecting) return '连接中…'
  if (props.recognizing) return '识别中…'
  if (props.listening) return '录音中…'
  return '强制暂停'
})
const canSend = computed(() => props.draft.trim().length > 0)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

/** 发送前从 DOM 同步 draft，避免仅改 DOM 未触发 input 时 voiceDraft 为空 */
function handleSend() {
  const fromDom = textareaRef.value?.value ?? props.draft
  if (!fromDom.trim()) return
  if (fromDom !== props.draft) emit('update:draft', fromDom)
  emit('send')
}

function syncDraftFromDom() {
  const fromDom = textareaRef.value?.value ?? ''
  if (fromDom !== props.draft) emit('update:draft', fromDom)
}
</script>

<template>
  <div
    class="wb-voice-dock"
    :class="{
      'wb-voice-dock--paused': micPaused,
      'wb-voice-dock--listening': listening && !micPaused,
      'wb-voice-dock--connecting': connecting && !micPaused,
      'wb-voice-dock--recognizing': recognizing && !micPaused,
    }"
  >
    <div class="wb-voice-dock__row" :class="{ 'wb-voice-dock__row--listening': listening && !micPaused }">
      <div class="wb-voice-dock__input-wrap">
        <textarea
          ref="textareaRef"
          :value="draft"
          class="wb-voice-dock__input"
          rows="1"
          :placeholder="listening && !micPaused ? '说或打字都行…' : '想说什么，直接打字…'"
          @input="emit('update:draft', ($event.target as HTMLTextAreaElement).value)"
          @focus="(e) => { syncDraftFromDom(); scrollInputIntoViewOnMobile(e.target as HTMLTextAreaElement) }"
          @keydown.enter.prevent="handleSend"
        />
        <button
          type="button"
          class="wb-voice-dock__send"
          :disabled="!canSend"
          title="发送文字"
          aria-label="发送"
          @click.stop="handleSend"
        >
          <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
      </div>
      <div
        v-if="(listening || connecting || recognizing) && !micPaused"
        class="wb-voice-dock__listen-badge"
        role="status"
      >
        <span
          class="wb-voice-dock__listen-dot"
          :class="{
            'wb-voice-dock__listen-dot--connecting': connecting,
            'wb-voice-dock__listen-dot--recognizing': recognizing && !connecting,
          }"
        />
        <span v-if="connecting">{{ connectingHint || '连接中…' }}</span>
        <span v-else-if="recognizing">识别中…</span>
        <span v-else>聆听</span>
      </div>
      <button
        type="button"
        class="wb-voice-dock__mic"
        :class="{
          'wb-voice-dock__mic--paused': micPaused,
          'wb-voice-dock__mic--live': listening && !micPaused && !connecting && !recognizing,
          'wb-voice-dock__mic--connecting': connecting && !micPaused,
          'wb-voice-dock__mic--recognizing': recognizing && !micPaused && !connecting,
        }"
        :title="micTitle"
        :aria-label="micTitle"
        @click.stop.prevent="emit('toggle-mic')"
      >
        <span v-if="connecting || recognizing" class="wb-voice-dock__mic-spinner" aria-hidden="true" />
        <svg v-else-if="micPaused" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M8 5v14l11-7z"/>
        </svg>
        <svg v-else viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <rect x="6" y="5" width="4" height="14" rx="1"/>
          <rect x="14" y="5" width="4" height="14" rx="1"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.wb-voice-dock {
  width: 100%;
  max-width: 720px;
  margin: 0 auto;
  padding: 0.65rem 1rem 0.85rem;
  box-sizing: border-box;
  pointer-events: auto;
}

.wb-voice-dock__row {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.wb-voice-dock__row--listening .wb-voice-dock__input-wrap {
  border-color: rgba(52, 211, 153, 0.28);
}

.wb-voice-dock__input-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 48px;
  padding: 0.35rem 0.5rem 0.35rem 0.85rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.wb-voice-dock__input {
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  color: var(--wb-text-primary, #f0f0f5);
  font-size: 0.92rem;
  line-height: 1.45;
  resize: none;
  outline: none;
  max-height: 88px;
}

.wb-voice-dock__send {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 50%;
  background: #0071e3;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  padding: 0;
}

.wb-voice-dock__send:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.wb-voice-dock__send svg {
  width: 18px;
  height: 18px;
}

.wb-voice-dock__listen-badge {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-shrink: 0;
  padding: 0 0.65rem;
  min-height: 36px;
  border-radius: 999px;
  background: rgba(52, 211, 153, 0.1);
  border: 1px solid rgba(52, 211, 153, 0.22);
  color: rgba(110, 231, 183, 0.95);
  font-size: 0.78rem;
  font-weight: 600;
}

.wb-voice-dock__listen-hint {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 48px;
  padding: 0 1rem;
  border-radius: 999px;
  background: rgba(52, 211, 153, 0.08);
  border: 1px solid rgba(52, 211, 153, 0.22);
  color: rgba(110, 231, 183, 0.95);
  font-size: 0.9rem;
  font-weight: 500;
}

.wb-voice-dock__listen-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #34d399;
  animation: wb-voice-dock-pulse 1.2s ease-in-out infinite;
}

.wb-voice-dock__mic {
  width: 52px;
  height: 52px;
  min-width: 52px;
  border-radius: 50%;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  padding: 0;
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.88);
  transition: background 0.15s, transform 0.15s, box-shadow 0.15s;
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
}

.wb-voice-dock__mic svg {
  width: 22px;
  height: 22px;
}

.wb-voice-dock__mic--live {
  background: rgba(52, 211, 153, 0.18);
  color: #6ee7b7;
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.12);
}

.wb-voice-dock__mic--connecting {
  background: rgba(129, 140, 248, 0.18);
  color: #a5b4fc;
  box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.12);
}

.wb-voice-dock__mic--recognizing {
  background: rgba(129, 140, 248, 0.18);
  color: #a5b4fc;
  box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.12);
}

.wb-voice-dock__mic-spinner {
  width: 22px;
  height: 22px;
  border: 2px solid rgba(255, 255, 255, 0.25);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: wb-voice-dock-spin 0.75s linear infinite;
}

.wb-voice-dock__listen-dot--connecting,
.wb-voice-dock__listen-dot--recognizing {
  background: #818cf8;
}

.wb-voice-dock__mic--paused {
  background: rgba(251, 191, 36, 0.18);
  color: #fbbf24;
  box-shadow: 0 0 0 3px rgba(251, 191, 36, 0.12);
}

.wb-voice-dock__mic:hover {
  transform: scale(1.04);
}

.wb-voice-dock--paused {
  background: rgba(251, 191, 36, 0.04);
  border-radius: 16px 16px 0 0;
}

@keyframes wb-voice-dock-pulse {
  0%,
  100% {
    opacity: 0.45;
    transform: scale(0.92);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes wb-voice-dock-spin {
  to {
    transform: rotate(360deg);
  }
}

html[data-workbench-theme='light'] .wb-voice-dock__input-wrap {
  background: rgba(0, 0, 0, 0.04);
  border-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .wb-voice-dock__input {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .wb-voice-dock__listen-hint {
  background: rgba(52, 211, 153, 0.1);
  border-color: rgba(52, 211, 153, 0.25);
  color: #059669;
}

html[data-workbench-theme='light'] .wb-voice-dock__mic {
  background: rgba(0, 0, 0, 0.06);
  color: #555;
}

html[data-workbench-theme='light'] .wb-voice-dock__mic--connecting,
html[data-workbench-theme='light'] .wb-voice-dock__mic--recognizing {
  background: rgba(0, 113, 227, 0.1);
  color: #0071e3;
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.12);
}

@media (max-width: 768px) {
  .wb-voice-dock {
    max-width: 100%;
    padding: 0.45rem 0.25rem 0.25rem;
  }

  .wb-voice-dock__row {
    gap: 0.5rem;
    flex-wrap: nowrap;
  }

  .wb-voice-dock__input-wrap {
    min-height: 52px;
    padding: 0.4rem 0.45rem 0.4rem 0.75rem;
  }

  .wb-voice-dock__input {
    font-size: 16px;
    line-height: 1.35;
  }

  .wb-voice-dock__listen-badge {
    display: none;
  }

  .wb-voice-dock__mic {
    width: 56px;
    height: 56px;
    min-width: 56px;
    min-height: 56px;
  }

  .wb-voice-dock__mic svg {
    width: 24px;
    height: 24px;
  }

  .wb-voice-dock__send {
    width: 44px;
    height: 44px;
    min-width: 44px;
    min-height: 44px;
  }
}
</style>
