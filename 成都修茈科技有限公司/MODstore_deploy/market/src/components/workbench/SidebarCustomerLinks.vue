<template>
  <div class="wb-sidebar-nav-links">
    <router-link
      v-for="item in items"
      :key="item.name"
      :to="{ name: item.name }"
      class="wb-sidebar-mode-btn"
      :class="{ 'wb-sidebar-mode-btn--active': routeName === item.name }"
      @click="$emit('navigate')"
    >
      <svg
        v-if="item.name === 'customer-service'"
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="1.4"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M3.5 7.5a4.5 4.5 0 019 0v1.5a1.5 1.5 0 01-1.5 1.5h-.5V7.5" />
        <path d="M3.5 7.5V9A1.5 1.5 0 005 10.5h.5M8 12.5v1M6.5 14h3" />
      </svg>
      <svg
        v-else-if="item.name === 'ai-store'"
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="1.4"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M3 2h10l-1.2 7.2a2 2 0 01-2 1.6H6.2a2 2 0 01-2-1.6L3 2zM5.5 13a1.5 1.5 0 003 0M3 2h10" />
      </svg>
      <svg
        v-else
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="1.3"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M2 4h12v9H2zM5 2h6v4H5zM5 9h6" />
      </svg>
      <span>{{ item.label }}</span>
    </router-link>
  </div>
</template>

<script setup lang="ts">
defineProps<{ routeName: string }>()
defineEmits<{ navigate: [] }>()

const items = [
  { name: 'customer-service', label: 'AI 客服' },
  { name: 'ai-store', label: 'AI 市场' },
  { name: 'customer-deliveries', label: '我的交付' },
] as const
</script>
