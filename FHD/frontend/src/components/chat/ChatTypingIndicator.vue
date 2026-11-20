<template>
  <div class="chat-typing-indicator" role="status" aria-live="polite" :aria-label="label || '正在输入'">
    <span v-for="i in 3" :key="i" class="chat-typing-indicator__dot" :style="{ animationDelay: `${(i - 1) * 0.16}s` }" />
    <span v-if="label" class="chat-typing-indicator__label">
      {{ label }}<template v-if="elapsedText"> {{ elapsedText }}</template>
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed, onActivated, ref, watchEffect } from 'vue'

const props = defineProps<{
  label?: string
  startedAt?: number
}>()

const now = ref(Date.now())
const refreshClock = () => { now.value = Date.now() }
onActivated(refreshClock)
watchEffect((cleanup) => {
  if (props.startedAt === undefined) return
  refreshClock()
  const timer = window.setInterval(refreshClock, 1000)
  cleanup(() => window.clearInterval(timer))
})

const elapsedText = computed(() => {
  if (props.startedAt === undefined) return ''
  const seconds = Math.max(0, Math.floor((now.value - props.startedAt) / 1000))
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
})
</script>
