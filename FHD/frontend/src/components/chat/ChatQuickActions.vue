<template>
  <div class="quick-actions" data-tour="chat-quick-actions">
    <button
      v-for="quickBtn in buttons"
      :key="quickBtn.text"
      class="quick-btn"
      :data-quick="quickBtn.text"
      :data-action="quickBtn.text === '测试预览' ? 'test-preview' : null"
      @click="$emit('quick', quickBtn.text)"
    >
      {{ quickBtn.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  buttons: Array<{ text: string; label: string }>
}>()

defineEmits<{
  quick: [text: string]
}>()
</script>
