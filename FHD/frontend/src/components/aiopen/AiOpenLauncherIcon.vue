<template>
  <svg
    class="aiopen-launcher-svg"
    viewBox="0 0 48 48"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <defs>
      <linearGradient id="aiopen-icon-bg" x1="8" y1="6" x2="40" y2="42" gradientUnits="userSpaceOnUse">
        <stop stop-color="#3b82f6" />
        <stop offset="1" stop-color="#1d4ed8" />
      </linearGradient>
      <linearGradient id="aiopen-icon-glow" x1="24" y1="10" x2="24" y2="38" gradientUnits="userSpaceOnUse">
        <stop stop-color="#ffffff" stop-opacity="0.95" />
        <stop offset="1" stop-color="#dbeafe" stop-opacity="0.85" />
      </linearGradient>
    </defs>
    <!-- 开放弧：OPEN 语义 -->
    <path
      d="M24 9.5c7.18 0 13 5.82 13 13 0 3.2-1.16 6.13-3.08 8.4"
      stroke="url(#aiopen-icon-glow)"
      stroke-width="2.8"
      stroke-linecap="round"
    />
    <path
      d="M24 35.5c-7.18 0-13-5.82-13-13 0-3.2 1.16-6.13 3.08-8.4"
      stroke="url(#aiopen-icon-glow)"
      stroke-width="2.8"
      stroke-linecap="round"
      opacity="0.55"
    />
    <!-- 虚拟光标十字 -->
    <circle cx="24" cy="24" r="4.2" fill="#ffffff" />
    <path d="M24 14.5v5.2M24 28.3v5.2M14.5 24h5.2M28.3 24h5.2" stroke="#ffffff" stroke-width="1.8" stroke-linecap="round" opacity="0.9" />
    <!-- MCP 接入节点 -->
    <circle cx="35.5" cy="14.5" r="2.2" fill="#93c5fd" />
    <circle cx="12.5" cy="33.5" r="2.2" fill="#93c5fd" />
    <path d="M33.8 16.2 26.5 21.8M14.8 31.8 21.2 26.2" stroke="#bfdbfe" stroke-width="1.4" stroke-linecap="round" />
  </svg>
</template>

<style scoped>
.aiopen-launcher-svg {
  width: 52px;
  height: 52px;
  display: block;
}
</style>
