<script setup lang="ts">
defineProps<{
  expertMode: boolean
}>()

const emit = defineEmits<{
  'update:expertMode': [value: boolean]
}>()
</script>

<template>
  <label class="mode-toggle">
    <input
      type="checkbox"
      :checked="expertMode"
      @change="emit('update:expertMode', ($event.target as HTMLInputElement).checked)"
    />
    <span>专家模式</span>
  </label>
</template>

<style scoped>
.mode-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8125rem;
  color: rgba(255, 255, 255, 0.65);
  cursor: pointer;
  user-select: none;
}
.mode-toggle input {
  accent-color: #4ade80;
}
</style>
