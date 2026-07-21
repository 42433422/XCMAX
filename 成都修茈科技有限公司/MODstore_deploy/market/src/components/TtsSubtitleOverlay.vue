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
          <p v-if="prev" class="tts-sub__line tts-sub__line--prev">
            <span class="tts-sub__zh">{{ prev.zh }}</span>
          </p>
          <div class="tts-sub__line tts-sub__line--cur">
            <p class="tts-sub__zh">{{ current.zh }}</p>
            <p v-if="current.en" class="tts-sub__en">{{ current.en }}</p>
            <p v-else class="tts-sub__en tts-sub__en--pending">Translating…</p>
          </div>
          <p v-if="next" class="tts-sub__line tts-sub__line--next">
            <span class="tts-sub__zh">{{ next.zh }}</span>
          </p>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { useTtsSubtitleStore } from '../composables/ttsSubtitleStore'

const { visible, current, prev, next, dismiss } = useTtsSubtitleStore()
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
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(18, 22, 32, 0.72) 0%, rgba(10, 12, 18, 0.82) 100%);
  backdrop-filter: blur(18px) saturate(1.2);
  -webkit-backdrop-filter: blur(18px) saturate(1.2);
  box-shadow:
    0 10px 40px rgba(0, 0, 0, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.1);
  pointer-events: none;
  text-align: center;
  color: #fff;
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
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.7);
  display: grid;
  place-items: center;
  cursor: pointer;
}

.tts-sub__close:hover {
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
}

.tts-sub__stack {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 64px;
  justify-content: center;
}

.tts-sub__line {
  margin: 0;
  transition: opacity 0.28s ease, transform 0.28s ease, filter 0.28s ease;
}

.tts-sub__line--prev,
.tts-sub__line--next {
  opacity: 0.28;
  filter: blur(0.2px);
  transform: scale(0.92);
}

.tts-sub__line--prev .tts-sub__zh,
.tts-sub__line--next .tts-sub__zh {
  font-size: 13px;
  font-weight: 500;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tts-sub__line--cur {
  opacity: 1;
  transform: scale(1);
}

.tts-sub__zh {
  margin: 0;
  font-size: clamp(17px, 2.4vw, 22px);
  font-weight: 650;
  letter-spacing: 0.02em;
  line-height: 1.45;
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.35);
}

.tts-sub__en {
  margin: 6px 0 0;
  font-size: clamp(12px, 1.6vw, 14px);
  font-weight: 450;
  line-height: 1.4;
  color: rgba(210, 220, 255, 0.88);
  letter-spacing: 0.01em;
}

.tts-sub__en--pending {
  opacity: 0.45;
  font-style: italic;
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
  .tts-sub__line,
  .tts-sub-enter-active,
  .tts-sub-leave-active {
    transition: none;
  }
}
</style>
