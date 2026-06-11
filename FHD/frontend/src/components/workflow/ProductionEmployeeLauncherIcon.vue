<template>
  <svg
    class="production-employee-launcher-svg"
    :class="{ 'production-employee-launcher-svg--sm': size === 'sm' }"
    viewBox="0 0 48 48"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <defs>
      <linearGradient id="prod-icon-helmet" x1="24" y1="10" x2="24" y2="22" gradientUnits="userSpaceOnUse">
        <stop stop-color="#ffffff" />
        <stop offset="1" stop-color="#fef3c7" stop-opacity="0.9" />
      </linearGradient>
      <linearGradient id="prod-icon-belt" x1="8" y1="36" x2="40" y2="36" gradientUnits="userSpaceOnUse">
        <stop stop-color="#ffffff" stop-opacity="0.45" />
        <stop offset="0.5" stop-color="#ffffff" stop-opacity="0.85" />
        <stop offset="1" stop-color="#ffffff" stop-opacity="0.45" />
      </linearGradient>
    </defs>
    <!-- 安全帽 -->
    <path
      d="M13 21.5c0-5.8 4.9-9.5 11-9.5s11 3.7 11 9.5"
      stroke="url(#prod-icon-helmet)"
      stroke-width="2.6"
      stroke-linecap="round"
    />
    <rect x="11.5" y="21" width="25" height="3.8" rx="1.8" fill="#ffffff" fill-opacity="0.92" />
    <!-- 员工轮廓 -->
    <circle cx="24" cy="28.5" r="4.2" fill="#ffffff" fill-opacity="0.88" />
    <path
      d="M16.5 32.5c1.8-2.6 4.6-4 7.5-4s5.7 1.4 7.5 4"
      stroke="#ffffff"
      stroke-width="2.4"
      stroke-linecap="round"
      fill="none"
    />
    <!-- 产线轨道 -->
    <rect x="7" y="37.5" width="34" height="3.2" rx="1.6" fill="url(#prod-icon-belt)" />
    <circle cx="13" cy="35.8" r="2.1" fill="#ffffff" fill-opacity="0.75" />
    <circle cx="24" cy="35.8" r="2.1" fill="#fde68a" />
    <circle cx="35" cy="35.8" r="2.1" fill="#ffffff" fill-opacity="0.75" />
    <!-- 齿轮：自动化生产 -->
    <circle cx="37.5" cy="14.5" r="3.2" stroke="#ffffff" stroke-width="1.6" stroke-opacity="0.85" />
    <path
      d="M37.5 10.8v1.6M37.5 16.6v1.6M33.8 14.5h1.6M39.6 14.5h1.6M34.8 11.8l1.1 1.1M39.1 16.1l1.1 1.1M40.2 11.8l-1.1 1.1M35.9 16.1l-1.1 1.1"
      stroke="#ffffff"
      stroke-width="1.4"
      stroke-linecap="round"
      stroke-opacity="0.9"
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
.production-employee-launcher-svg {
  width: 52px;
  height: 52px;
  display: block;
}
.production-employee-launcher-svg--sm {
  width: 28px;
  height: 28px;
}
</style>
