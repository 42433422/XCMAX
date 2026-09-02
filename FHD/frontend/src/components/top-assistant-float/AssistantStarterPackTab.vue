<script setup>
// 新手对话包列表：由 TopAssistantFloat.vue 模板机械切分而来（行为保持不变）。
defineProps({
  presets: { type: Array, default: () => [] },
})

defineEmits(['select'])
</script>

<template>
  <div class="assistant-body assistant-body-starter">
    <div class="starter-pack-list">
      <button
        v-for="(item, idx) in presets"
        :key="idx"
        type="button"
        class="starter-pack-item"
        @click="$emit('select', item.text)"
      >
        <div class="starter-pack-label">{{ item.label }}</div>
        <div class="starter-pack-hint">{{ item.hint }}</div>
      </button>
    </div>
  </div>
</template>

<style scoped src="./top-assistant-float.css"></style>
