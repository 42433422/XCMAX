<script setup lang="ts">
defineProps<{
  workflowName: string
  saving: boolean
  isActive: boolean
}>()

defineEmits<{
  (e: 'back'): void
  (e: 'rename'): void
  (e: 'auto-layout'): void
  (e: 'sandbox'): void
  (e: 'execute'): void
  (e: 'toggle-active'): void
  (e: 'publish'): void
  (e: 'versions'): void
  (e: 'save-as-template'): void
}>()
</script>

<template>
  <header class="wf2-toolbar">
    <div class="wf2-toolbar__left">
      <button class="wf2-tb-btn wf2-tb-btn--ghost" type="button" @click="$emit('back')">
        <span class="wf2-tb-btn__icon">←</span>
        <span>返回列表</span>
      </button>
      <div class="wf2-toolbar__title-wrap">
        <h2 class="wf2-toolbar__title" @click="$emit('rename')" :title="'点击修改'">
          {{ workflowName || '未命名工作流' }}
        </h2>
        <svg class="wf2-toolbar__edit-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
      </div>
      <span
        class="wf2-toolbar__status"
        :class="{ 'wf2-toolbar__status--ok': isActive }"
      >
        <span class="wf2-toolbar__status-dot" />
        {{ isActive ? '已激活' : '未激活' }}
      </span>
      <span v-if="saving" class="wf2-toolbar__saving">
        <span class="wf2-toolbar__spinner" />
        保存中…
      </span>
      <span v-else class="wf2-toolbar__saved">已保存</span>
    </div>
    <div class="wf2-toolbar__right">
      <button class="wf2-tb-btn" type="button" @click="$emit('toggle-active')">
        {{ isActive ? '停用' : '激活' }}
      </button>
      <button class="wf2-tb-btn" type="button" @click="$emit('auto-layout')">自动布局</button>
      <button class="wf2-tb-btn" type="button" @click="$emit('versions')">版本历史</button>
      <button class="wf2-tb-btn" type="button" @click="$emit('publish')">发布版本</button>
      <button class="wf2-tb-btn" type="button" @click="$emit('save-as-template')">另存为模板</button>
      <button class="wf2-tb-btn" type="button" @click="$emit('sandbox')">沙盒测试</button>
      <button class="wf2-tb-btn wf2-tb-btn--primary" type="button" @click="$emit('execute')">
        <span class="wf2-tb-btn__icon">▶</span>
        立即执行
      </button>
    </div>
  </header>
</template>

<style scoped>
.wf2-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 20px;
  background: rgba(15, 23, 42, 0.88);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  position: relative;
  z-index: 10;
}

.wf2-toolbar__left,
.wf2-toolbar__right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.wf2-toolbar__title-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
  transition: background 0.2s ease;
}

.wf2-toolbar__title-wrap:hover {
  background: rgba(148, 163, 184, 0.1);
}

.wf2-toolbar__title-wrap:hover .wf2-toolbar__edit-icon {
  opacity: 1;
}

.wf2-toolbar__title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: #f1f5f9;
}

.wf2-toolbar__edit-icon {
  opacity: 0;
  color: #94a3b8;
  transition: opacity 0.2s ease;
}

.wf2-toolbar__status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  background: rgba(148, 163, 184, 0.1);
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.12);
}

.wf2-toolbar__status--ok {
  background: rgba(34, 197, 94, 0.12);
  color: #4ade80;
  border-color: rgba(34, 197, 94, 0.2);
  box-shadow: 0 0 12px rgba(34, 197, 94, 0.1);
}

.wf2-toolbar__status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.wf2-toolbar__saving {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #fbbf24;
}

.wf2-toolbar__saved {
  font-size: 12px;
  color: #64748b;
}

.wf2-toolbar__spinner {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(251, 191, 36, 0.2);
  border-top-color: #fbbf24;
  border-radius: 50%;
  animation: wf2-spin 0.8s linear infinite;
}

@keyframes wf2-spin {
  to {
    transform: rotate(360deg);
  }
}

.wf2-tb-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  font-weight: 500;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(30, 41, 59, 0.5);
  color: #cbd5e1;
  padding: 7px 14px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.wf2-tb-btn:hover {
  background: rgba(148, 163, 184, 0.12);
  color: #f1f5f9;
  border-color: rgba(148, 163, 184, 0.25);
}

.wf2-tb-btn--ghost {
  background: transparent;
  border-color: transparent;
  color: #94a3b8;
  padding: 7px 10px;
}

.wf2-tb-btn--ghost:hover {
  background: rgba(148, 163, 184, 0.1);
  color: #e2e8f0;
}

.wf2-tb-btn--primary {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-color: transparent;
  color: #fff;
  font-weight: 600;
  box-shadow: 0 0 20px rgba(99, 102, 241, 0.25);
}

.wf2-tb-btn--primary:hover {
  background: linear-gradient(135deg, #4f46e5, #7c3aed);
  box-shadow: 0 0 28px rgba(99, 102, 241, 0.4);
  transform: translateY(-1px);
}

.wf2-tb-btn__icon {
  font-size: 11px;
}
</style>
