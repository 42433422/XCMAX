<template>
  <Teleport to="body">
    <Transition name="tts-sub">
      <div
        v-if="visible && current"
        class="tts-sub"
        role="status"
        aria-live="polite"
        aria-label="朗读字幕"
      >
        <button type="button" class="tts-sub__close" aria-label="关闭字幕" title="关闭" @click="dismiss">
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" aria-hidden="true">
            <path d="M4 4l8 8M12 4L4 12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
          </svg>
        </button>
        <div class="tts-sub__stack">
          <p class="tts-sub__zh">{{ current.zh }}</p>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { useTtsSubtitleStore } from '../composables/ttsSubtitleStore'

const { visible, current, dismiss } = useTtsSubtitleStore()
</script>

<style scoped>
.tts-sub {
  position: fixed;
  left: 50%;
  bottom: max(28px, env(safe-area-inset-bottom, 0px) + 16px);
  transform: translateX(-50%);
  z-index: 9200;
  width: min(720px, calc(100vw - 32px));
  padding: 14px 40px 16px 20px;
  background: transparent;
  border: 0;
  box-shadow: none;
  pointer-events: none;
  text-align: center;
  color: #111;
}

.tts-sub__close {
  pointer-events: auto;
  position: absolute;
  top: 10px;
  right: 10px;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: rgba(17, 17, 17, 0.72);
  display: grid;
  place-items: center;
  cursor: pointer;
  text-shadow: 0 1px 0 rgba(255, 255, 255, 0.85);
}

.tts-sub__close:hover {
  color: #000;
}

.tts-sub__stack {
  display: flex;
  flex-direction: column;
  min-height: 40px;
  justify-content: center;
}

.tts-sub__zh {
  margin: 0;
  font-size: clamp(17px, 2.4vw, 22px);
  font-weight: 650;
  letter-spacing: 0.02em;
  line-height: 1.45;
  color: #111;
  text-shadow:
    0 1px 0 rgba(255, 255, 255, 0.95),
    0 0 10px rgba(255, 255, 255, 0.55);
}

.tts-sub-enter-active,
.tts-sub-leave-active {
  transition: opacity 0.28s ease, transform 0.28s ease;
}

.tts-sub-enter-from,
.tts-sub-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(16px);
}

@media (prefers-reduced-motion: reduce) {
  .tts-sub,
  .tts-sub-enter-active,
  .tts-sub-leave-active {
    transition: none;
  }
}
</style>
