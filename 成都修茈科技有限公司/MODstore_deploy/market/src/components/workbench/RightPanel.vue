<template>
  <Teleport to="body">
    <div v-if="visible" class="rp-backdrop" @click="$emit('close')" />
    <aside
      class="rp"
      :class="{ 'rp--open': visible }"
      role="complementary"
      :aria-label="panelTitle"
    >
      <header class="rp-head">
        <h2 class="rp-title">{{ panelTitle }}</h2>
        <button type="button" class="rp-close" aria-label="关闭" @click="$emit('close')">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
        </button>
      </header>

      <div class="rp-body">
        <template v-if="panelType === 'make'">
          <div class="rp-starters">
            <button
              v-for="s in starters"
              :key="s.id"
              type="button"
              class="rp-starter"
              :class="{ 'rp-starter--active': activeStarter === s.id }"
              @click="activeStarter = s.id"
            >
              <span class="rp-starter__name">{{ s.label }}</span>
              <span class="rp-starter__sub">{{ s.sub }}</span>
            </button>
          </div>

          <div class="rp-input">
            <textarea
              v-model="makeDraft"
              class="rp-textarea"
              rows="3"
              placeholder="描述你想制作的内容…"
              @keydown.enter.meta="onSendMake"
            />
            <button
              type="button"
              class="rp-send"
              :class="{ 'rp-send--ready': makeDraft.trim() }"
              :disabled="!makeDraft.trim()"
              @click="onSendMake"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" /></svg>
            </button>
          </div>
        </template>

        <template v-if="panelType === 'voice'">
          <div class="rp-orb-wrap">
            <div class="rp-orb" :class="{ 'rp-orb--pulse': voiceState === 'listening' }" />
          </div>

          <p class="rp-voice-status">{{ voiceStatusText }}</p>

          <div class="rp-voice-actions">
            <button type="button" class="rp-voice-btn rp-voice-btn--primary" @click="$emit('start-voice')">
              {{ voiceState === 'listening' ? '正在聆听…' : '开始说话' }}
            </button>
            <button
              type="button"
              class="rp-voice-btn rp-voice-btn--secondary"
              :disabled="!voiceDraft.trim()"
              @click="onSendVoice"
            >
              发送文字
            </button>
            <button
              type="button"
              class="rp-voice-btn rp-voice-btn--secondary"
              @click="$emit('confirm-voice')"
            >
              确认并制作
            </button>
          </div>

          <div class="rp-input">
            <textarea
              v-model="voiceDraft"
              class="rp-textarea"
              rows="2"
              placeholder="或直接输入文字…"
              @keydown.enter.meta="onSendVoice"
            />
          </div>
        </template>
      </div>
    </aside>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = withDefaults(
  defineProps<{
    visible: boolean
    panelType: 'make' | 'voice' | ''
  }>(),
  {
    visible: false,
    panelType: ''
  }
)

const emit = defineEmits<{
  close: []
  'send-make': [text: string, intent: string]
  'send-voice': [text: string]
  'start-voice': []
  'confirm-voice': []
}>()

const activeStarter = ref<'mod' | 'employee' | 'skill'>('skill')
const voiceState = ref<'idle' | 'listening' | 'thinking' | 'summary'>('idle')
const makeDraft = ref('')
const voiceDraft = ref('')

const starters = [
  { id: 'mod' as const, label: '做 Mod', sub: '先建仓库·行业JSON·员工命名' },
  { id: 'employee' as const, label: '做员工', sub: '提示词与工具·填入描述' },
  { id: 'skill' as const, label: '生成 Skill 组', sub: '画布编排·先拆Skill再组合' }
]

const panelTitle = computed(() => {
  if (props.panelType === 'make') return '制作'
  if (props.panelType === 'voice') return '语音'
  return ''
})

const voiceStatusText = computed(() => {
  const map: Record<string, string> = {
    idle: '点击下方按钮开始语音输入',
    listening: '正在聆听…',
    thinking: '思考中…',
    summary: '语音已转写，可编辑后发送'
  }
  return map[voiceState.value]
})

function onSendMake() {
  const text = makeDraft.value.trim()
  if (!text) return
  const intentMap: Record<string, string> = {
    mod: 'create_mod',
    employee: 'create_employee',
    skill: 'create_skill_group'
  }
  emit('send-make', text, intentMap[activeStarter.value])
  makeDraft.value = ''
}

function onSendVoice() {
  const text = voiceDraft.value.trim()
  if (!text) return
  emit('send-voice', text)
  voiceDraft.value = ''
}
</script>

<style scoped>
.rp-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: rgba(0, 0, 0, 0.3);
}

.rp {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 91;
  width: 380px;
  display: flex;
  flex-direction: column;
  background: #0a0a0a;
  border-left: 1px solid rgba(255, 255, 255, 0.06);
  transform: translateX(100%);
  transition: transform 200ms cubic-bezier(0.4, 0, 0.2, 1);
}

.rp--open {
  transform: translateX(0);
  transition: transform 300ms cubic-bezier(0.4, 0, 0.2, 1);
}

.rp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.rp-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--wb-text-primary, #fff);
}

.rp-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--wb-radius-sm, 6px);
  background: transparent;
  color: var(--wb-text-muted, rgba(255, 255, 255, 0.5));
  cursor: pointer;
  transition: background var(--wb-transition-fast, 0.15s ease);
}

.rp-close:hover {
  background: rgba(255, 255, 255, 0.06);
}

.rp-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.rp-starters {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rp-starter {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.03);
  cursor: pointer;
  text-align: left;
  transition: background 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
}

.rp-starter:hover {
  background: rgba(255, 255, 255, 0.06);
  transform: translateY(-2px);
}

.rp-starter--active {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.18);
}

.rp-starter--active:hover {
  background: rgba(255, 255, 255, 0.06);
}

.rp-starter__name {
  font-size: 14px;
  font-weight: 600;
  color: var(--wb-text-primary, #fff);
}

.rp-starter__sub {
  font-size: 12px;
  color: var(--wb-text-muted, rgba(255, 255, 255, 0.5));
}

.rp-input {
  position: relative;
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.rp-textarea {
  flex: 1;
  resize: none;
  padding: 12px 16px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 24px;
  background: #2f2f2f;
  color: var(--wb-text-primary, #fff);
  font-size: 14px;
  line-height: 1.5;
  font-family: inherit;
  outline: none;
  transition: border-color var(--wb-transition-fast, 0.15s ease);
}

.rp-textarea:focus {
  border-color: rgba(255, 255, 255, 0.18);
}

.rp-textarea::placeholder {
  color: var(--wb-text-muted, rgba(255, 255, 255, 0.5));
}

.rp-send {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.2s ease, color 0.2s ease;
}

.rp-send--ready {
  background: #fff;
  color: #0a0a0a;
}

.rp-send:disabled {
  cursor: default;
}

.rp-orb-wrap {
  display: flex;
  justify-content: center;
  padding: 24px 0 8px;
}

.rp-orb {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  background: rgba(129, 140, 248, 0.15);
  transition: box-shadow 0.3s ease;
}

.rp-orb--pulse {
  animation: rp-pulse 2.5s ease-in-out infinite;
  box-shadow: 0 0 40px rgba(129, 140, 248, 0.2);
}

@keyframes rp-pulse {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.02);
  }
}

.rp-voice-status {
  text-align: center;
  font-size: 13px;
  color: var(--wb-text-muted, rgba(255, 255, 255, 0.5));
  margin: 0;
}

.rp-voice-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rp-voice-btn {
  width: 100%;
  padding: 10px 0;
  border: none;
  border-radius: var(--wb-radius-md, 10px);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s ease, opacity 0.2s ease;
}

.rp-voice-btn--primary {
  background: var(--wb-accent-primary, #818cf8);
  color: #fff;
}

.rp-voice-btn--primary:hover {
  opacity: 0.9;
}

.rp-voice-btn--secondary {
  background: rgba(255, 255, 255, 0.06);
  color: var(--wb-text-primary, #fff);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.rp-voice-btn--secondary:hover {
  background: rgba(255, 255, 255, 0.1);
}

.rp-voice-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

html[data-workbench-theme='light'] .rp-backdrop {
  background: rgba(0, 0, 0, 0.15);
}

html[data-workbench-theme='light'] .rp {
  background: #ffffff;
  border-left-color: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .rp-head {
  border-bottom-color: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .rp-title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .rp-close {
  color: #86868b;
}

html[data-workbench-theme='light'] .rp-close:hover {
  background: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .rp-starter {
  border-color: rgba(0, 0, 0, 0.06);
  background: rgba(0, 0, 0, 0.03);
}

html[data-workbench-theme='light'] .rp-starter:hover {
  background: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .rp-starter--active {
  background: rgba(0, 0, 0, 0.06);
  border-color: rgba(0, 0, 0, 0.12);
}

html[data-workbench-theme='light'] .rp-starter--active:hover {
  background: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .rp-starter__name {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .rp-starter__sub {
  color: #86868b;
}

html[data-workbench-theme='light'] .rp-textarea {
  border-color: rgba(0, 0, 0, 0.08);
  background: #ffffff;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .rp-textarea:focus {
  border-color: rgba(0, 0, 0, 0.15);
}

html[data-workbench-theme='light'] .rp-textarea::placeholder {
  color: #86868b;
}

html[data-workbench-theme='light'] .rp-send {
  background: rgba(0, 0, 0, 0.08);
  color: #86868b;
}

html[data-workbench-theme='light'] .rp-send--ready {
  background: #0071e3;
  color: #ffffff;
}

html[data-workbench-theme='light'] .rp-voice-status {
  color: #86868b;
}

html[data-workbench-theme='light'] .rp-voice-btn--primary {
  background: #0071e3;
  color: #ffffff;
}

html[data-workbench-theme='light'] .rp-voice-btn--secondary {
  background: rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
  border-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .rp-voice-btn--secondary:hover {
  background: rgba(0, 0, 0, 0.08);
}
</style>
