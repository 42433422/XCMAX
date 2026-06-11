<template>
  <svg
    class="modstore-launcher-svg"
    :class="{ 'modstore-launcher-svg--sm': size === 'sm' }"
    viewBox="0 0 48 48"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <defs>
      <linearGradient id="modstore-tile-a" x1="14" y1="16" x2="14" y2="26" gradientUnits="userSpaceOnUse">
        <stop stop-color="#ffffff" stop-opacity="0.95" />
        <stop offset="1" stop-color="#ede9fe" stop-opacity="0.72" />
      </linearGradient>
      <linearGradient id="modstore-tile-b" x1="34" y1="16" x2="34" y2="26" gradientUnits="userSpaceOnUse">
        <stop stop-color="#ffffff" />
        <stop offset="1" stop-color="#ddd6fe" stop-opacity="0.78" />
      </linearGradient>
      <linearGradient id="modstore-tile-c" x1="14" y1="28" x2="14" y2="38" gradientUnits="userSpaceOnUse">
        <stop stop-color="#ffffff" stop-opacity="0.88" />
        <stop offset="1" stop-color="#ede9fe" stop-opacity="0.62" />
      </linearGradient>
      <linearGradient id="modstore-tile-d" x1="34" y1="28" x2="34" y2="38" gradientUnits="userSpaceOnUse">
        <stop stop-color="#ffffff" stop-opacity="0.82" />
        <stop offset="1" stop-color="#ddd6fe" stop-opacity="0.58" />
      </linearGradient>
    </defs>
    <!-- 商店外框 -->
    <rect
      x="9"
      y="11"
      width="30"
      height="30"
      rx="7"
      stroke="#ffffff"
      stroke-width="2.4"
      stroke-opacity="0.55"
    />
    <!-- 2×2 MOD 格子 -->
    <rect x="12.5" y="14.5" width="11" height="11" rx="2.8" fill="url(#modstore-tile-a)" />
    <rect x="24.5" y="14.5" width="11" height="11" rx="2.8" fill="url(#modstore-tile-b)" />
    <rect x="12.5" y="26.5" width="11" height="11" rx="2.8" fill="url(#modstore-tile-c)" />
    <rect x="24.5" y="26.5" width="11" height="11" rx="2.8" fill="url(#modstore-tile-d)" />
    <!-- 左上：员工包 -->
    <circle cx="18" cy="18.2" r="2" fill="#ffffff" fill-opacity="0.92" />
    <path
      d="M15.2 21.8c.9-1.2 2-1.8 2.8-1.8s1.9.6 2.8 1.8"
      stroke="#ffffff"
      stroke-width="1.6"
      stroke-linecap="round"
      fill="none"
      opacity="0.92"
    />
    <!-- 右上：安装 + -->
    <path
      d="M30 20v4.8M27.6 22.4h4.8"
      stroke="#ffffff"
      stroke-width="2"
      stroke-linecap="round"
      opacity="0.95"
    />
    <!-- 左下：文档行 -->
    <path
      d="M14.8 30.2h6.4M14.8 33.2h4.6"
      stroke="#ffffff"
      stroke-width="1.5"
      stroke-linecap="round"
      opacity="0.78"
    />
    <!-- 右下：扩展块 -->
    <path
      d="M27.2 29.8h3.2v3.2M30.4 29.8v3.2M27.2 33h3.2"
      stroke="#ffffff"
      stroke-width="1.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      opacity="0.78"
    />
    <!-- 下载角标 -->
    <circle cx="36.5" cy="12.5" r="4.8" fill="#ffffff" fill-opacity="0.96" />
    <path
      d="M36.5 10.4v3.6M34.8 12.8l1.7 1.7 1.7-1.7"
      stroke="#7c3aed"
      stroke-width="1.6"
      stroke-linecap="round"
      stroke-linejoin="round"
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
.modstore-launcher-svg {
  width: 52px;
  height: 52px;
  display: block;
}
.modstore-launcher-svg--sm {
  width: 28px;
  height: 28px;
}
</style>
