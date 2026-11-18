<template>
  <Teleport to="body">
    <div
      v-if="cursorVisible"
      class="aiopen-cursor"
      :class="{ 'aiopen-cursor--clicking': cursorClicking }"
      :style="{ transform: `translate(${cursorX}px, ${cursorY}px) rotate(${cursorTilt}deg)` }"
      aria-hidden="true"
    >
      <svg class="aiopen-cursor-arrow" width="26" height="26" viewBox="0 0 24 24">
        <defs>
          <linearGradient id="aiopen-cursor-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#60a5fa" />
            <stop offset="100%" stop-color="#1d4ed8" />
          </linearGradient>
        </defs>
        <path
          d="M4 2 L4 19 L8.5 15.2 L11.5 21.5 L14.2 20.2 L11.2 14 L17 13.6 Z"
          fill="url(#aiopen-cursor-grad)"
          stroke="#ffffff"
          stroke-width="1.5"
          stroke-linejoin="round"
        />
      </svg>
      <span v-if="cursorActionLabel" class="aiopen-cursor-label">AI {{ cursorActionLabel }}</span>
      <span v-if="cursorClicking" class="aiopen-cursor-ripple"></span>
    </div>
    <div v-if="enabled && connected && agentActive" class="aiopen-control-badge" title="外部 AI Agent 正在操作本页面">
      <span class="aiopen-control-dot"></span>
      AI 正在操作本页
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
  cursorTilt,
  aiopenCursorEnabled as enabled,
  aiopenCursorConnected as connected,
  aiopenAgentActive as agentActive,
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
  /* 带一点回弹的缓动，移动末端更自然 */
  transition: transform 520ms cubic-bezier(0.16, 1, 0.3, 1);
  will-change: transform;
}
.aiopen-cursor-arrow {
  display: block;
  transition: transform 180ms ease;
  filter: drop-shadow(0 0 6px rgba(59, 130, 246, 0.55))
    drop-shadow(0 2px 4px rgba(15, 23, 42, 0.35));
}
.aiopen-cursor--clicking .aiopen-cursor-arrow {
  transform: scale(0.78) rotate(-8deg);
}
.aiopen-cursor-label {
  position: absolute;
  top: 24px;
  left: 16px;
  white-space: nowrap;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: #ffffff;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 999px;
  padding: 3px 10px;
  box-shadow: 0 4px 12px rgba(29, 78, 216, 0.35);
  animation: aiopen-label-in 180ms cubic-bezier(0.16, 1, 0.3, 1);
}
.aiopen-cursor-ripple {
  position: absolute;
  top: -10px;
  left: -10px;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 2px solid rgba(59, 130, 246, 0.75);
  box-shadow: 0 0 0 6px rgba(59, 130, 246, 0.12);
  animation: aiopen-ripple 520ms cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes aiopen-label-in {
  from {
    opacity: 0;
    transform: translateY(-4px) scale(0.92);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
@keyframes aiopen-ripple {
  from {
    transform: scale(0.25);
    opacity: 0.9;
  }
  to {
    transform: scale(1.5);
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
