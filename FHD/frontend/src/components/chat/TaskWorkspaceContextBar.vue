<script setup lang="ts">
defineProps<{
  title: string
  stage?: string
  progress?: number
}>()
</script>

<template>
  <section class="chat-workspace-context" aria-label="当前独立工作区">
    <div>
      <span>独立对话工作区</span>
      <h1>{{ title }}</h1>
    </div>
    <div class="chat-workspace-context__state">
      <strong>{{ stage || '正在同步工作区' }}</strong>
      <span v-if="typeof progress === 'number'">{{ progress }}%</span>
    </div>
  </section>
</template>

<style scoped>
.chat-workspace-context {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin: 0 0 10px;
  padding: 12px 16px;
  border: 1px solid var(--xc-color-border);
  border-radius: var(--xc-radius-lg);
  background: linear-gradient(110deg, var(--xc-color-primary-surface), var(--xc-color-surface));
}

.chat-workspace-context > div:first-child > span {
  color: var(--xc-color-primary);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .08em;
}

.chat-workspace-context h1 { margin: 2px 0 0; font-size: var(--xc-font-lg); }
.chat-workspace-context__state { display: flex; align-items: center; gap: 10px; color: var(--xc-color-muted); font-size: var(--xc-font-xs); }
.chat-workspace-context__state strong { color: var(--xc-color-text-secondary); font-weight: 600; }
</style>
