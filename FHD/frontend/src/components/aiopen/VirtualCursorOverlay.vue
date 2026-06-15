<template>
  <Teleport to="body">
    <div
      v-if="cursorVisible"
      class="aiopen-cursor"
      :class="{ 'aiopen-cursor--clicking': cursorClicking }"
      :style="{ transform: `translate(${cursorX}px, ${cursorY}px)` }"
      aria-hidden="true"
    >
      <svg class="aiopen-cursor-arrow" width="24" height="24" viewBox="0 0 24 24">
        <path d="M4 2 L4 19 L8.5 15.2 L11.5 21.5 L14.2 20.2 L11.2 14 L17 13.6 Z" fill="#2563eb" stroke="#ffffff" stroke-width="1.4" />
      </svg>
      <span v-if="cursorActionLabel" class="aiopen-cursor-label">AI {{ cursorActionLabel }}</span>
      <span v-if="cursorClicking" class="aiopen-cursor-ripple"></span>
    </div>
    <div v-if="enabled && connected" class="aiopen-control-badge" title="外部 AI Agent 可经 AIOPEN 操控本页面">
      <span class="aiopen-control-dot"></span>
      AI 操控通道已连接
    </div>
  </Teleport>
</template>

<script setup>
import { useRouter } from 'vue-router'
import {
  cursorX,
  cursorY,
  cursorVisible,
  cursorClicking,
  cursorActionLabel,
  aiopenCursorEnabled as enabled,
  aiopenCursorConnected as connected,
  initAiOpenCursor,
} from '@/composables/useAiOpenCursor'

const router = useRouter()
initAiOpenCursor(router)
</script>

<style scoped>
.aiopen-cursor {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 99999;
  pointer-events: none;
  transition: transform 480ms cubic-bezier(0.22, 1, 0.36, 1);
  will-change: transform;
}
.aiopen-cursor-arrow {
  display: block;
  filter: drop-shadow(0 2px 4px rgba(15, 23, 42, 0.35));
}
.aiopen-cursor--clicking .aiopen-cursor-arrow {
  transform: scale(0.85);
}
.aiopen-cursor-label {
  position: absolute;
  top: 22px;
  left: 14px;
  white-space: nowrap;
  font-size: 11px;
  font-weight: 600;
  color: #ffffff;
  background: #2563eb;
  border-radius: 999px;
  padding: 2px 8px;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.35);
}
.aiopen-cursor-ripple {
  position: absolute;
  top: -8px;
  left: -8px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 2px solid rgba(37, 99, 235, 0.7);
  animation: aiopen-ripple 480ms ease-out;
}
@keyframes aiopen-ripple {
  from {
    transform: scale(0.3);
    opacity: 1;
  }
  to {
    transform: scale(1.4);
    opacity: 0;
  }
}
.aiopen-control-badge {
  position: fixed;
  right: 14px;
  bottom: 14px;
  z-index: 99998;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 600;
  color: #1d4ed8;
  background: rgba(239, 246, 255, 0.95);
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  padding: 5px 12px;
  box-shadow: 0 4px 12px rgba(30, 64, 175, 0.15);
  pointer-events: none;
}
.aiopen-control-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
  animation: aiopen-pulse 1.6s ease-in-out infinite;
}
@keyframes aiopen-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}
</style>
