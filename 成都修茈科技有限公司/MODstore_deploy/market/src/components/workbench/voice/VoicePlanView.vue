<template>
  <div class="voice-plan-view">
    <div class="voice-plan-view__orb-area">
      <div
        class="voice-plan-view__orb"
        :class="`voice-plan-view__orb--${voiceState}`"
        @click="handleOrbClick"
      >
        <div class="voice-plan-view__orb-glow"></div>
        <div class="voice-plan-view__orb-core"></div>
      </div>
    </div>

    <h2 class="voice-plan-view__title">{{ titleText }}</h2>
    <p class="voice-plan-view__subtitle">
      点击呼吸球开始语音规划。浏览器不支持语音时，可用下方文字补充。
    </p>

    <div class="voice-plan-view__actions">
      <button
        class="voice-plan-view__btn voice-plan-view__btn--primary"
        @click="emit('start-voice')"
      >
        开始说话
      </button>
      <button
        class="voice-plan-view__btn voice-plan-view__btn--secondary"
        :disabled="voiceState === 'idle'"
        @click="emit('send-text', fallbackText)"
      >
        发送文字
      </button>
      <button
        class="voice-plan-view__btn voice-plan-view__btn--secondary"
        :disabled="voiceState !== 'summary'"
        @click="emit('confirm')"
      >
        确认并制作
      </button>
    </div>

    <div class="voice-plan-view__fallback">
      <textarea
        v-model="fallbackText"
        class="voice-plan-view__textarea"
        placeholder="输入文字描述你想制作的内容…"
        rows="3"
      ></textarea>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

type VoiceState = 'idle' | 'listening' | 'thinking' | 'summary'

const voiceState = ref<VoiceState>('idle')
const fallbackText = ref('')

const emit = defineEmits<{
  'start-voice': []
  'send-text': [text: string]
  confirm: []
}>()

const titleText = computed(() => {
  const map: Record<VoiceState, string> = {
    idle: '说出你想制作的东西',
    listening: '正在聆听…',
    thinking: '正在思考…',
    summary: '确认你的规划',
  }
  return map[voiceState.value]
})

function handleOrbClick() {
  if (voiceState.value === 'idle') {
    voiceState.value = 'listening'
    emit('start-voice')
  } else if (voiceState.value === 'listening') {
    voiceState.value = 'thinking'
  } else if (voiceState.value === 'thinking') {
    voiceState.value = 'summary'
  } else {
    voiceState.value = 'idle'
  }
}
</script>

<style scoped>
.voice-plan-view {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 16px;
  padding: 32px 24px;
}

.voice-plan-view__orb-area {
  position: relative;
  width: 200px;
  height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
}

.voice-plan-view__orb {
  position: relative;
  width: 200px;
  height: 200px;
  border-radius: 50%;
  cursor: pointer;
  transition: transform var(--wb-transition-normal);
}

.voice-plan-view__orb:hover {
  transform: scale(1.04);
}

.voice-plan-view__orb:active {
  transform: scale(0.97);
}

.voice-plan-view__orb-glow {
  position: absolute;
  inset: -12%;
  border-radius: 50%;
  opacity: 0.5;
  transition:
    background var(--wb-transition-slow),
    box-shadow var(--wb-transition-slow);
  pointer-events: none;
}

.voice-plan-view__orb-core {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  transition:
    background var(--wb-transition-slow),
    box-shadow var(--wb-transition-slow);
  animation: voiceOrbPulse 2s ease-in-out infinite;
}

.voice-plan-view__orb--idle .voice-plan-view__orb-core {
  background: radial-gradient(
    circle at 35% 35%,
    rgba(200, 255, 255, 0.9) 0%,
    rgba(0, 255, 255, 0.55) 18%,
    rgba(0, 180, 255, 0.28) 42%,
    rgba(0, 80, 140, 0.1) 72%,
    transparent 100%
  );
  box-shadow:
    0 0 48px rgba(0, 255, 255, 0.6),
    0 0 96px rgba(0, 200, 255, 0.35),
    inset 0 0 40px rgba(0, 255, 255, 0.3);
}

.voice-plan-view__orb--idle .voice-plan-view__orb-glow {
  background: radial-gradient(circle, rgba(0, 255, 255, 0.15), transparent 70%);
  box-shadow: 0 0 60px rgba(0, 255, 255, 0.2);
}

.voice-plan-view__orb--listening .voice-plan-view__orb-core {
  background: radial-gradient(
    circle at 35% 35%,
    rgba(200, 255, 220, 0.92) 0%,
    rgba(74, 222, 128, 0.6) 18%,
    rgba(34, 197, 94, 0.3) 42%,
    rgba(22, 163, 74, 0.12) 72%,
    transparent 100%
  );
  box-shadow:
    0 0 48px rgba(74, 222, 128, 0.65),
    0 0 96px rgba(34, 197, 94, 0.4),
    inset 0 0 40px rgba(74, 222, 128, 0.35);
  animation: voiceOrbPulseListening 1.2s ease-in-out infinite;
}

.voice-plan-view__orb--listening .voice-plan-view__orb-glow {
  background: radial-gradient(circle, rgba(74, 222, 128, 0.2), transparent 70%);
  box-shadow: 0 0 80px rgba(74, 222, 128, 0.3);
}

.voice-plan-view__orb--thinking .voice-plan-view__orb-core {
  background: radial-gradient(
    circle at 35% 35%,
    rgba(255, 245, 200, 0.92) 0%,
    rgba(251, 191, 36, 0.6) 18%,
    rgba(245, 158, 11, 0.3) 42%,
    rgba(217, 119, 6, 0.12) 72%,
    transparent 100%
  );
  box-shadow:
    0 0 48px rgba(251, 191, 36, 0.65),
    0 0 96px rgba(245, 158, 11, 0.4),
    inset 0 0 40px rgba(251, 191, 36, 0.35);
  animation: voiceOrbPulseThinking 1.5s ease-in-out infinite;
}

.voice-plan-view__orb--thinking .voice-plan-view__orb-glow {
  background: radial-gradient(circle, rgba(251, 191, 36, 0.2), transparent 70%);
  box-shadow: 0 0 80px rgba(251, 191, 36, 0.3);
}

.voice-plan-view__orb--summary .voice-plan-view__orb-core {
  background: radial-gradient(
    circle at 35% 35%,
    rgba(220, 210, 255, 0.92) 0%,
    rgba(129, 140, 248, 0.6) 18%,
    rgba(99, 102, 241, 0.3) 42%,
    rgba(79, 70, 229, 0.12) 72%,
    transparent 100%
  );
  box-shadow:
    0 0 48px rgba(129, 140, 248, 0.65),
    0 0 96px rgba(99, 102, 241, 0.4),
    inset 0 0 40px rgba(129, 140, 248, 0.35);
}

.voice-plan-view__orb--summary .voice-plan-view__orb-glow {
  background: radial-gradient(circle, rgba(129, 140, 248, 0.2), transparent 70%);
  box-shadow: 0 0 80px rgba(129, 140, 248, 0.3);
}

@keyframes voiceOrbPulse {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.05);
  }
}

@keyframes voiceOrbPulseListening {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.08);
  }
}

@keyframes voiceOrbPulseThinking {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.06);
  }
}

.voice-plan-view__title {
  font-size: 20px;
  font-weight: 600;
  color: var(--wb-text-primary);
  text-align: center;
  margin: 0;
  transition: color var(--wb-transition-normal);
}

.voice-plan-view__subtitle {
  font-size: 13px;
  color: var(--wb-text-muted);
  text-align: center;
  margin: 0;
  max-width: 380px;
  line-height: 1.6;
}

.voice-plan-view__actions {
  display: flex;
  gap: 12px;
  margin-top: 8px;
}

.voice-plan-view__btn {
  border: none;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  padding: 10px 24px;
  border-radius: 999px;
  transition:
    background var(--wb-transition-fast),
    opacity var(--wb-transition-fast),
    box-shadow var(--wb-transition-fast),
    transform var(--wb-transition-fast);
  outline: none;
}

.voice-plan-view__btn:focus-visible {
  box-shadow: var(--shadow-focus);
}

.voice-plan-view__btn:active:not(:disabled) {
  transform: scale(0.96);
}

.voice-plan-view__btn--primary {
  background: var(--wb-gradient-accent);
  color: #fff;
  box-shadow: 0 4px 16px rgba(124, 58, 237, 0.35);
}

.voice-plan-view__btn--primary:hover {
  background: var(--wb-gradient-accent-hover);
  box-shadow: 0 6px 24px rgba(124, 58, 237, 0.45);
}

.voice-plan-view__btn--secondary {
  background: var(--wb-surface-elevated);
  color: var(--wb-text-primary);
  border: 1px solid var(--wb-border-default);
}

.voice-plan-view__btn--secondary:hover:not(:disabled) {
  background: var(--wb-card-hover-bg);
  border-color: var(--wb-card-hover-border);
}

.voice-plan-view__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.voice-plan-view__fallback {
  width: 100%;
  max-width: 460px;
  margin-top: 8px;
}

.voice-plan-view__textarea {
  width: 100%;
  resize: vertical;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.6;
  padding: 12px 16px;
  border-radius: var(--wb-input-radius);
  border: 1px solid var(--wb-input-border);
  background: var(--wb-input-bg);
  color: var(--wb-text-primary);
  outline: none;
  transition:
    border-color var(--wb-transition-fast),
    box-shadow var(--wb-transition-fast);
  box-sizing: border-box;
}

.voice-plan-view__textarea::placeholder {
  color: var(--wb-text-muted);
}

.voice-plan-view__textarea:focus {
  border-color: var(--wb-accent-primary);
  box-shadow: 0 0 0 3px var(--wb-accent-soft);
}

@media (prefers-reduced-motion: reduce) {
  .voice-plan-view__orb-core {
    animation: none !important;
  }
}
</style>
