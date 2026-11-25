<script setup lang="ts">
/**
 * 管家面板底部输入区（语音 / 截图 / 文本输入 / 发送）。
 *
 * 由 FloatingAgentPanel.vue 模板块机械切分而来（行为与视觉保持不变）：
 * footer 元素与隐藏图片 input 留在入口，这里按 corpMode 分支渲染输入条；
 * textarea 高度自适应在组件内完成（经 expose 供入口在语音插入文本后调用）。
 */
import { computed, onMounted, ref, watch } from 'vue'
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
const canSend = computed(() => Boolean(props.draft.trim() || props.hasPendingImage) && !agentStore.isLoading && !props.imagePicking)

function send() {
  if (canSend.value) emit('send')
}

function handleComposerEnter(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229 || event.defaultPrevented) return
  event.preventDefault()
  send()
}

function onDraftInput(ev: Event) {
  const value = (ev.target as HTMLTextAreaElement).value
  emit('update:draft', value)
  autoResize()
}

function autoResize() {
  const ta = textareaRef.value
  if (!ta) return
  ta.style.height = 'auto'
  ta.style.height = Math.min(ta.scrollHeight, 120) + 'px'
}

// Also resize when the host clears the draft, inserts voice text, or switches layouts.
watch(() => [props.draft, props.corpMode], autoResize, { flush: 'post' })
onMounted(autoResize)

defineExpose({ autoResize })
</script>

<template>
  <div class="panel-composer-layout" :class="{ 'panel-composer-layout--corp': corpMode }">
    <div class="panel-tools" :class="{ 'panel-tools--corp': corpMode }">
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
        :class="{ 'panel-shot-btn--active': hasPendingImage, 'panel-shot-btn--light': isLightTheme || corpMode }"
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
    <div class="panel-composer" :class="{ 'panel-composer--corp': corpMode }">
      <div class="panel-input-shell" :class="{ 'panel-input-shell--autonomy': !corpMode && !!$slots.autonomy }">
        <textarea
          ref="textareaRef"
          :value="draft"
          class="panel-input"
          placeholder="说点什么…"
          rows="1"
          aria-label="发送消息"
          @keydown.enter.exact="handleComposerEnter"
          @input="onDraftInput"
        />
        <slot v-if="!corpMode" name="autonomy" />
      </div>
      <button type="button" class="panel-send" :disabled="!canSend" aria-label="发送" @click="send">
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped src="./floatingAgentPanel.css"></style>
