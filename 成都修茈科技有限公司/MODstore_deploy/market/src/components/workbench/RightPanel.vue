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

<!-- 拆分后本文件为组装入口（façade）：样式外移至 ./RightPanel.css，模板与逻辑保持原样。 -->
<style scoped src="./RightPanel.css"></style>
