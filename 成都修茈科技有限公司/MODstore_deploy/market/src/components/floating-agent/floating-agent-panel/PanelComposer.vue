<script setup lang="ts">
/**
 * 管家面板底部输入区（语音 / 截图 / 文本输入 / 发送）。
 *
 * 由 FloatingAgentPanel.vue 模板块机械切分而来（行为与视觉保持不变）：
 * footer 元素与隐藏图片 input 留在入口，这里按 corpMode 分支渲染输入条；
 * textarea 高度自适应在组件内完成（经 expose 供入口在语音插入文本后调用）。
 */
import { ref } from 'vue'
import { useAgentStore } from '../../../stores/agent'
import type { VoiceState } from '../../../composables/agent/useVoiceInput'
import AgentVoiceInput from '../AgentVoiceInput.vue'

const props = defineProps<{
  corpMode: boolean
  isLightTheme: boolean
  draft: string
  hasPendingImage: boolean
  imagePicking: boolean
  voiceState: VoiceState
  isSupported: boolean
  error: string
  loadingHint?: string
  sessionReady?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:draft', v: string): void
  (e: 'toggle-voice'): void
  (e: 'pick-image'): void
  (e: 'send'): void
}>()

const agentStore = useAgentStore()

const textareaRef = ref<HTMLTextAreaElement | null>(null)

function onDraftInput(ev: Event) {
  const value = (ev.target as HTMLTextAreaElement).value
  emit('update:draft', value)
  autoResize()
}

function autoResize() {
  const ta = textareaRef.value
  if (!ta) return
  ta.style.height = 'auto'
  ta.style.height = Math.min(ta.scrollHeight, 80) + 'px'
}

defineExpose({ autoResize })
</script>

<template>
  <template v-if="corpMode">
    <div class="panel-composer panel-composer--corp">
      <AgentVoiceInput
        :voice-state="voiceState"
        :is-supported="isSupported"
        :error="error"
        :loading-hint="loadingHint"
        :session-ready="sessionReady"
        @toggle="$emit('toggle-voice')"
      />
      <button
        type="button"
        class="panel-shot-btn"
        :class="{
          'panel-shot-btn--active': hasPendingImage,
          'panel-shot-btn--light': isLightTheme || corpMode,
        }"
        :aria-pressed="hasPendingImage"
        aria-label="上传图片"
        :title="hasPendingImage ? '已选图：再次点击可更换' : '点击上传图片发给 AI（需 vision 模型）'"
        :disabled="imagePicking"
        @click="$emit('pick-image')"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3" y="5" width="18" height="14" rx="2.5" stroke="currentColor" stroke-width="1.8" />
          <circle cx="8.5" cy="10" r="1.6" fill="currentColor" />
          <path d="M3.5 16.5 9 12l3.2 2.8L15 12l5.5 4.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
      <textarea
        ref="textareaRef"
        :value="draft"
        class="panel-input"
        placeholder="说点什么…"
        rows="1"
        aria-label="发送消息"
        @keydown.enter.exact.prevent="$emit('send')"
        @input="onDraftInput"
      />
      <button
        type="button"
        class="panel-send"
        :disabled="(!draft.trim() && !hasPendingImage) || agentStore.isLoading || imagePicking"
        aria-label="发送"
        @click="$emit('send')"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
  </template>
  <template v-else>
    <div class="panel-tools">
      <AgentVoiceInput
        :voice-state="voiceState"
        :is-supported="isSupported"
        :error="error"
        :loading-hint="loadingHint"
        :session-ready="sessionReady"
        @toggle="$emit('toggle-voice')"
      />
      <button
        type="button"
        class="panel-shot-btn"
        :class="{
          'panel-shot-btn--active': hasPendingImage,
          'panel-shot-btn--light': isLightTheme,
        }"
        :aria-pressed="hasPendingImage"
        aria-label="上传图片"
        :title="hasPendingImage ? '已选图：再次点击可更换' : '点击上传图片发给 AI（需 vision 模型）'"
        :disabled="imagePicking"
        @click="$emit('pick-image')"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3" y="5" width="18" height="14" rx="2.5" stroke="currentColor" stroke-width="1.8" />
          <circle cx="8.5" cy="10" r="1.6" fill="currentColor" />
          <path d="M3.5 16.5 9 12l3.2 2.8L15 12l5.5 4.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </div>
    <div class="panel-composer">
      <textarea
        ref="textareaRef"
        :value="draft"
        class="panel-input"
        placeholder="说点什么…"
        rows="1"
        aria-label="发送消息"
        @keydown.enter.exact.prevent="$emit('send')"
        @input="onDraftInput"
      />
      <button
        type="button"
        class="panel-send"
        :disabled="(!draft.trim() && !hasPendingImage) || agentStore.isLoading || imagePicking"
        aria-label="发送"
        @click="$emit('send')"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
  </template>
</template>

<style scoped src="./floatingAgentPanel.css"></style>
