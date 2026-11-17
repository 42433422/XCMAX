<template>
  <nav class="admin-section-nav" :aria-label="label">
    <button v-for="item in items" :key="item.value" type="button"
      :aria-pressed="modelValue === item.value" @click="$emit('update:modelValue', item.value)">{{ item.label }}</button>
  </nav>
</template>
<script setup lang="ts">
defineProps<{ modelValue: string; items: Array<{ value: string; label: string }>; label: string }>()
defineEmits<{ (event: 'update:modelValue', value: string): void }>()
</script>
