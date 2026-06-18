<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';

const route = useRoute();
const router = useRouter();

const tabs = [
  { name: 'chat', label: '对话', icon: 'fa-comments', to: { name: 'chat' as const } },
  { name: 'discover', label: '发现', icon: 'fa-compass', to: { name: 'discover' as const } },
  { name: 'im', label: '信息', icon: 'fa-envelope-o', to: { name: 'im' as const } },
  { name: 'mod-store', label: '市场', icon: 'fa-puzzle-piece', to: { name: 'mod-store' as const } },
  { name: 'settings', label: '我的', icon: 'fa-user', to: { name: 'settings' as const } },
];

const activeName = computed(() => {
  const name = String(route.name || '');
  if (name === 'chat') return 'chat';
  if (name === 'discover') return 'discover';
  if (name === 'im') return 'im';
  if (name === 'mod-store') return 'mod-store';
  if (name === 'settings') return 'settings';
  return '';
});

function isActive(tabName: string) {
  return activeName.value === tabName;
}

function go(tab: (typeof tabs)[number]) {
  if (isActive(tab.name)) return;
  void router.push(tab.to);
}
</script>

<template>
  <nav class="mobile-bottom-nav" aria-label="主导航">
    <button
      v-for="tab in tabs"
      :key="tab.name"
      type="button"
      class="mobile-bottom-nav__item"
      :class="{ active: isActive(tab.name) }"
      :aria-current="isActive(tab.name) ? 'page' : undefined"
      @click="go(tab)"
    >
      <i class="fa" :class="tab.icon" aria-hidden="true"></i>
      <span>{{ tab.label }}</span>
    </button>
  </nav>
</template>

<style scoped>
.mobile-bottom-nav {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 120;
  display: none;
  grid-template-columns: repeat(5, 1fr);
  align-items: stretch;
  min-height: 56px;
  padding-bottom: env(safe-area-inset-bottom, 0);
  background: var(--xc-color-surface);
  border-top: 1px solid var(--xc-color-border);
  box-shadow: 0 -4px 16px rgba(10, 20, 50, 0.06);
}

.mobile-bottom-nav__item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  border: 0;
  background: transparent;
  color: var(--xc-color-muted);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  padding: 6px 0 8px;
  transition:
    color var(--xc-transition-fast),
    transform var(--xc-transition-fast);
}

.mobile-bottom-nav__item .fa {
  font-size: 18px;
}

.mobile-bottom-nav__item.active {
  color: var(--xc-color-primary);
  font-weight: var(--xc-font-weight-semibold);
}

.mobile-bottom-nav__item:active {
  transform: scale(0.98);
}

@media (max-width: 768px) {
  .mobile-bottom-nav {
    display: grid;
  }
}
</style>
