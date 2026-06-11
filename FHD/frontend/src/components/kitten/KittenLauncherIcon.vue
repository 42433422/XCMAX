<template>
  <svg
    class="kitten-launcher-svg"
    :class="{ 'kitten-launcher-svg--sm': size === 'sm' }"
    viewBox="0 0 48 48"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <defs>
      <linearGradient id="smart-icon-bar-1" x1="10" y1="34" x2="10" y2="24" gradientUnits="userSpaceOnUse">
        <stop stop-color="#ffffff" stop-opacity="0.72" />
        <stop offset="1" stop-color="#ffffff" stop-opacity="0.45" />
      </linearGradient>
      <linearGradient id="smart-icon-bar-2" x1="20" y1="36" x2="20" y2="18" gradientUnits="userSpaceOnUse">
        <stop stop-color="#ffffff" stop-opacity="0.88" />
        <stop offset="1" stop-color="#ffffff" stop-opacity="0.62" />
      </linearGradient>
      <linearGradient id="smart-icon-bar-3" x1="30" y1="38" x2="30" y2="14" gradientUnits="userSpaceOnUse">
        <stop stop-color="#ffffff" />
        <stop offset="1" stop-color="#e0f2fe" stop-opacity="0.85" />
      </linearGradient>
      <linearGradient id="smart-icon-line" x1="8" y1="32" x2="40" y2="16" gradientUnits="userSpaceOnUse">
        <stop stop-color="#fef08a" />
        <stop offset="1" stop-color="#ffffff" />
      </linearGradient>
    </defs>
    <!-- 数据网格 -->
    <path
      d="M8 12h32M8 20h32M8 28h32M8 36h32M16 8v32M24 8v32M32 8v32"
      stroke="#ffffff"
      stroke-opacity="0.12"
      stroke-width="0.8"
    />
    <!-- 柱状 -->
    <rect x="9" y="28" width="6" height="10" rx="1.4" fill="url(#smart-icon-bar-1)" />
    <rect x="19" y="22" width="6" height="16" rx="1.4" fill="url(#smart-icon-bar-2)" />
    <rect x="29" y="16" width="6" height="22" rx="1.4" fill="url(#smart-icon-bar-3)" />
    <!-- 趋势线 -->
    <path
      d="M11 32.5 21 24.5 32 18.5 38 14.5"
      stroke="url(#smart-icon-line)"
      stroke-width="2.2"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <circle cx="38" cy="14.5" r="2" fill="#ffffff" stroke="#fef08a" stroke-width="1.2" />
    <!-- 智慧 spark -->
    <path
      d="M34.5 9.5 35.8 12.2 38.5 13.5 35.8 14.8 34.5 17.5 33.2 14.8 30.5 13.5 33.2 12.2 34.5 9.5Z"
      fill="#ffffff"
      fill-opacity="0.95"
    />
  </svg>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    size?: 'md' | 'sm'
  }>(),
  { size: 'md' },
)
</script>

<style scoped>
.kitten-launcher-svg {
  width: 52px;
  height: 52px;
  display: block;
}
.kitten-launcher-svg--sm {
  width: 28px;
  height: 28px;
}
</style>
