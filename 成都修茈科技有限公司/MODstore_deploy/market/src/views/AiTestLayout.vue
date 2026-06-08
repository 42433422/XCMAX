<template>
  <div class="ai-test-layout">
    <nav class="ai-test-tabs" aria-label="AI 测试">
      <router-link
        :to="{ name: 'ai-test-sandbox' }"
        class="ai-test-tab"
        :class="{ 'ai-test-tab--active': activeTab === 'sandbox' }"
      >
        沙箱
      </router-link>
      <router-link
        :to="{ name: 'ai-test-exam' }"
        class="ai-test-tab"
        :class="{ 'ai-test-tab--active': activeTab === 'exam' }"
      >
        AI 员工考试
      </router-link>
    </nav>
    <div class="ai-test-body">
      <router-view />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const activeTab = computed(() => (route.name === 'ai-test-exam' ? 'exam' : 'sandbox'))
</script>

<style scoped>
.ai-test-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--color-bg-base, #0f0f0f);
}

.ai-test-tabs {
  display: flex;
  gap: 4px;
  padding: 8px 16px 0;
  flex-shrink: 0;
  border-bottom: 0.5px solid var(--color-border-subtle, rgba(255, 255, 255, 0.1));
  background: var(--color-bg-elevated, #1a1a1a);
}

.ai-test-tab {
  padding: 8px 16px;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--color-text-muted, rgba(255, 255, 255, 0.55));
  text-decoration: none;
  border-radius: 8px 8px 0 0;
  border: 0.5px solid transparent;
  border-bottom: none;
  margin-bottom: -0.5px;
  transition: color 0.15s, background 0.15s;
}

.ai-test-tab:hover {
  color: var(--color-text-primary, #fff);
  background: rgba(255, 255, 255, 0.04);
}

.ai-test-tab--active {
  color: var(--color-text-primary, #fff);
  background: var(--color-bg-base, #0f0f0f);
  border-color: var(--color-border-subtle, rgba(255, 255, 255, 0.12));
}

.ai-test-body {
  flex: 1 1 0%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

html[data-workbench-theme='light'] .ai-test-layout {
  background: #f5f5f7;
}

html[data-workbench-theme='light'] .ai-test-tabs {
  background: #ffffff;
  border-bottom-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .ai-test-tab {
  color: #86868b;
}

html[data-workbench-theme='light'] .ai-test-tab:hover,
html[data-workbench-theme='light'] .ai-test-tab--active {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .ai-test-tab--active {
  background: #f5f5f7;
  border-color: rgba(0, 0, 0, 0.08);
}
</style>
