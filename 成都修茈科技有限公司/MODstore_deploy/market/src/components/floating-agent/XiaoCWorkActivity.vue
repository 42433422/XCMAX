<script setup lang="ts">
import { ref } from 'vue'
import XiaoCDeliveryFollowups from './XiaoCDeliveryFollowups.vue'
import XiaoCMemoryList from './XiaoCMemoryList.vue'

defineProps<{ light?: boolean; ticketId?: number }>()
const section = ref<'delivery' | 'memory'>('delivery')
</script>

<template>
  <section class="xiaoc-activity" :class="{ 'xiaoc-activity--light': light }" aria-label="小 C 工作动态">
    <nav class="xiaoc-activity__sections" aria-label="工作动态功能">
      <button type="button" :aria-pressed="section === 'delivery'" @click="section = 'delivery'">交付跟进</button>
      <button type="button" :aria-pressed="section === 'memory'" @click="section = 'memory'">我的记忆</button>
    </nav>
    <XiaoCDeliveryFollowups v-if="section === 'delivery'" :ticket-id="ticketId" />
    <XiaoCMemoryList v-else />
  </section>
</template>

<style scoped>
.xiaoc-activity {
  --xiaoc-border: #343c49;
  --xiaoc-muted: #adb8c9;
  --xiaoc-accent: #a0c4ff;
  --xiaoc-alert: #ffba9d;
  --xiaoc-bg: #171d28;
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
  font-size: .84rem;
  color: #e9eff8;
  overflow-wrap: anywhere;
}
.xiaoc-activity--light {
  --xiaoc-border: #cdd6e2;
  --xiaoc-muted: #46556b;
  --xiaoc-accent: #184994;
  --xiaoc-alert: #8a311d;
  --xiaoc-bg: #f2f6fc;
  color: #18283d;
}
.xiaoc-activity__sections {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
}
.xiaoc-activity :deep(button) {
  padding: 5px 9px;
  border: 1px solid var(--xiaoc-border);
  border-radius: 7px;
  background: var(--xiaoc-bg);
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.xiaoc-activity :deep(button[aria-pressed='true']) {
  border-color: var(--xiaoc-accent);
  color: var(--xiaoc-accent);
}
.xiaoc-activity :deep(button:disabled) {
  opacity: .55;
  cursor: default;
}
.xiaoc-activity :deep(.xiaoc-toolbar) {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0;
}
.xiaoc-activity :deep(.xiaoc-muted) { color: var(--xiaoc-muted); }
.xiaoc-activity :deep(.xiaoc-error) { color: var(--xiaoc-alert); }
</style>
