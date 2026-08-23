<template>
  <div class="chat-typing-indicator" role="status" aria-live="polite" :aria-label="label || '正在输入'">
    <span v-for="i in 3" :key="i" class="chat-typing-indicator__dot" :style="{ animationDelay: `${(i - 1) * 0.16}s` }" />
    <span v-if="label" class="chat-typing-indicator__label">
      {{ label }}<template v-if="showElapsed"> {{ elapsedText }}</template>
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps<{
  label?: string
  /** Codex 风格：展示已思考耗时（秒），随流式实时累加。 */
  showElapsed?: boolean
}>()

const elapsedSeconds = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  if (!props.showElapsed) return
  timer = setInterval(() => {
    elapsedSeconds.value += 1
  }, 1000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

const elapsedText = computed(() => formatElapsed(elapsedSeconds.value))

function formatElapsed(total: number): string {
  if (total < 60) return `${total}s`
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}m ${seconds}s`
}
</script>
