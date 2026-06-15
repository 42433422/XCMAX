<template>
  <div class="chat-typing-indicator" role="status" aria-live="polite" :aria-label="label || '正在输入'">
    <span v-for="i in 3" :key="i" class="chat-typing-indicator__dot" :style="{ animationDelay: `${(i - 1) * 0.16}s` }" />
    <span v-if="label" class="chat-typing-indicator__label">{{ label }}</span>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  label?: string
}>()
</script>
