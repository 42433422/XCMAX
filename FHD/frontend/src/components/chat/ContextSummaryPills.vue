<template>
  <div class="context-summary-pills">
    <span
      v-for="item in displayItems"
      :key="item"
      class="context-summary-pill"
    >
      {{ item }}
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  summary?: unknown
}>()

const displayItems = computed(() => {
  const raw = props.summary
  if (Array.isArray(raw)) return raw.map((item) => String(item || '').trim()).filter(Boolean)
  if (raw && typeof raw === 'object') {
    const obj = raw as Record<string, unknown>
    const items = Array.isArray(obj.items)
      ? obj.items.map((item) => String(item || '').trim()).filter(Boolean)
      : []
    if (items.length) return items
    const text = String(obj.text || obj.label || '').trim()
    return text ? [text] : []
  }
  const text = String(raw || '').trim()
  return text ? [text] : []
})
</script>

<style scoped>
.context-summary-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.context-summary-pill {
  border-radius: 999px;
  background: rgba(33, 150, 243, 0.12);
  color: #1565c0;
  font-size: 12px;
  padding: 3px 8px;
}
</style>
