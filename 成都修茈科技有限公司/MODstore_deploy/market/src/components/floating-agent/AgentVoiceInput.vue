<template>
  <div class="voice-bar">
    <button
      v-if="isSupported"
      type="button"
      class="voice-btn"
      :class="{ 'voice-btn--active': isListening, 'voice-btn--light': isLightTheme }"
      :aria-label="isListening ? '停止录音' : '按住说话'"
      :title="isSupported ? (isListening ? '点击停止录音' : '点击开始语音输入') : '浏览器不支持语音识别'"
      @click="toggle"
    >
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="9" y="2" width="6" height="12" rx="3" stroke="currentColor" stroke-width="1.8" />
        <path d="M5 11a7 7 0 0 0 14 0" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        <line x1="12" y1="18" x2="12" y2="22" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
      </svg>
    </button>
    <span v-if="statusHint" class="voice-hint">{{ statusHint }}</span>
    <span v-else-if="error" class="voice-err">{{ error }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { VoiceState } from '../../composables/agent/useVoiceInput'
import { useWorkbenchTheme } from '../../composables/useWorkbenchTheme'

const props = defineProps<{
  voiceState: VoiceState
  isSupported: boolean
  error: string
  loadingHint?: string
  sessionReady?: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle'): void
}>()

const { isLightTheme } = useWorkbenchTheme()
const isListening = computed(() => props.voiceState === 'listening')

const statusHint = computed(() => {
  if (props.error) return ''
  if (props.voiceState === 'thinking') return '正在处理…'
  if (!isListening.value) return ''
  if (props.loadingHint) return props.loadingHint
  if (props.sessionReady === false) return '正在连接…'
  return '请说话，说完再点麦克风结束'
})

function toggle() {
  emit('toggle')
}
</script>

<style scoped>
.voice-bar {
  display: flex;
  align-items: center;
  gap: 6px;
}

.voice-btn {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.55);
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.voice-btn svg {
  width: 18px;
  height: 18px;
}

.voice-btn:hover {
  background: rgba(255, 255, 255, 0.09);
  color: rgba(255, 255, 255, 0.85);
}

.voice-btn--active {
  background: rgba(0, 220, 255, 0.15);
  border-color: rgba(0, 220, 255, 0.45);
  color: #00dcff;
  animation: voice-pulse 1.2s ease-in-out infinite;
}

.voice-btn--light {
  border-color: rgba(148, 163, 184, 0.5);
  background: #f1f5f9;
  color: #475569;
}

.voice-btn--light:hover {
  background: #e2e8f0;
  color: #1e3a8a;
}

.voice-btn--light.voice-btn--active {
  background: rgba(37, 99, 235, 0.12);
  border-color: rgba(37, 99, 235, 0.5);
  color: #2563eb;
  animation: voice-pulse-light 1.2s ease-in-out infinite;
}

@keyframes voice-pulse-light {
  0%, 100% { box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.28); }
  50% { box-shadow: 0 0 0 5px rgba(37, 99, 235, 0); }
}

.voice-hint {
  font-size: 0.72rem;
  color: rgba(148, 163, 184, 0.95);
  flex: 1;
  line-height: 1.3;
  max-width: 200px;
}

.voice-btn--light ~ .voice-hint {
  color: #64748b;
}

.voice-err {
  font-size: 0.72rem;
  color: #f87171;
  flex: 1;
}

@keyframes voice-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(0, 220, 255, 0.3); }
  50% { box-shadow: 0 0 0 5px rgba(0, 220, 255, 0); }
}
</style>
