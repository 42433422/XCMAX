<script setup lang="ts">
import packageJson from '../../../package.json'

defineProps<{
  visible: boolean
  hideChrome: boolean
  primaryModName: string
  startupModNames: string[]
  modsLoading: boolean
  modsLoadError: unknown
  startupProgressPct: number
}>()

const emit = defineEmits<{
  skip: []
}>()

const appVersion = `v${packageJson.version || '10.0.0'}`

function startupPublicUrl(fileName: string) {
  const base = String(import.meta.env.BASE_URL || '/')
  return `${base}startup/${fileName}`.replace(/([^:]\/)\/+/g, '$1')
}
</script>

<template>
  <div
    v-if="visible && !hideChrome"
    class="startup-splash"
    aria-label="初始化动画，点击跳过"
    title="点击屏幕快速进入"
    @pointerdown.stop="emit('skip')"
  >
    <div class="startup-splash-inner">
      <div class="startup-logo-wrap">
        <img class="startup-logo-base" :src="startupPublicUrl('xc-logo-base.jpg')" alt="XC logo" />
        <img class="startup-logo-text" :src="startupPublicUrl('xc-logo-text.jpg')" alt="XC logo with text" />
      </div>
      <div v-if="primaryModName" class="startup-mod-title">
        {{ primaryModName }}
      </div>
      <div v-if="visible" class="startup-mod-chips-wrap">
        <template v-if="startupModNames.length > 1">
          <div class="startup-mod-chips-hint">已加载扩展包</div>
          <div class="startup-mod-chips">
            <span
              v-for="modName in startupModNames"
              :key="modName"
              class="startup-mod-chip"
            >
              {{ modName }}
            </span>
          </div>
        </template>
        <div v-else class="startup-mod-status">
          <div v-if="primaryModName" class="mod-loaded">
            <i class="fa fa-check-circle" aria-hidden="true"></i>
            <span>当前扩展包：{{ primaryModName }}</span>
          </div>
          <div v-else-if="modsLoading" class="mod-loading">
            <i class="fa fa-spinner fa-spin" aria-hidden="true"></i>
            <span>正在加载扩展包...</span>
          </div>
          <div v-else-if="modsLoadError" class="mod-error">
            <i class="fa fa-exclamation-circle" aria-hidden="true"></i>
            <span>扩展包加载异常</span>
          </div>
          <div v-else class="mod-loading">
            <i class="fa fa-circle-o-notch fa-spin" aria-hidden="true"></i>
            <span>正在初始化...</span>
          </div>
        </div>
      </div>
      <div v-if="visible" class="startup-progress-wrap" aria-hidden="true">
        <div class="startup-progress-track">
          <div
            class="startup-progress-fill"
            :style="{ width: `${startupProgressPct}%` }"
          ></div>
        </div>
      </div>
    </div>
    <div class="startup-version" aria-label="当前版本">{{ appVersion }}</div>
  </div>
</template>

<style scoped>
.startup-splash {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: grid;
  place-items: center;
  background:
    radial-gradient(circle at 28% 20%, rgba(255, 255, 255, 0.9), transparent 30%),
    linear-gradient(135deg, #edf5fb 0%, #e7eef6 48%, #eef3f8 100%);
  opacity: 1;
  visibility: visible;
  transition: opacity 360ms ease, visibility 0s linear 360ms;
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  overflow: hidden;
}

.startup-splash::before,
.startup-splash::after {
  content: "";
  position: absolute;
  pointer-events: none;
  display: none;
}

.startup-splash.hide {
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
}

.startup-splash-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  max-width: min(480px, 92vw);
  padding: 0 var(--app-space-md);
  position: relative;
  z-index: 1;
  animation: startupContentEnter 520ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
}

.startup-version {
  position: absolute;
  left: 24px;
  bottom: 20px;
  z-index: 1;
  padding: 7px 11px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(23, 32, 51, 0.56);
  background: rgba(255, 255, 255, 0.46);
  border: 1px solid rgba(255, 255, 255, 0.64);
  box-shadow:
    0 8px 20px rgba(15, 76, 129, 0.07),
    inset 0 1px 0 rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(12px);
  pointer-events: none;
  user-select: none;
  -webkit-user-select: none;
}

.startup-logo-wrap {
  width: min(380px, 68vw);
  aspect-ratio: 1 / 1;
  position: relative;
  display: grid;
  place-items: center;
  border-radius: 28px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.9) 0%, rgba(248, 251, 255, 0.76) 100%);
  border: 1px solid rgba(255, 255, 255, 0.78);
  box-shadow:
    0 20px 50px rgba(15, 76, 129, 0.12),
    0 8px 18px rgba(15, 76, 129, 0.06),
    inset 0 1px 0 rgba(255, 255, 255, 0.95);
  overflow: hidden;
}

.startup-logo-wrap img {
  position: absolute;
  inset: 8%;
  width: 84%;
  height: 84%;
  object-fit: contain;
  user-select: none;
  -webkit-user-drag: none;
  z-index: 1;
}

.startup-logo-base {
  opacity: 1;
}

.startup-logo-text {
  opacity: 0;
  animation: startupTextFadeIn 1200ms ease 450ms forwards;
}

@keyframes startupTextFadeIn {
  from {
    opacity: 0;
    transform: translateY(6px) scale(0.985);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.startup-mod-title {
  font-size: 24px;
  font-weight: 700;
  color: #172033;
  text-align: center;
  margin-top: 10px;
  letter-spacing: -0.02em;
  animation: startupSoftEnter 800ms ease 600ms forwards;
  opacity: 0;
}

.startup-progress-wrap {
  width: 100%;
  max-width: min(420px, 84vw);
  margin-top: 10px;
  animation: startupSoftEnter 500ms ease 200ms forwards;
  opacity: 0;
}

.startup-progress-track {
  height: 5px;
  border-radius: 999px;
  background: rgba(15, 76, 129, 0.1);
  overflow: hidden;
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.08);
}

.startup-progress-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #0b63ce 0%, #12bde6 62%, #62d9ff 100%);
  transition: width 120ms ease-out;
}

.startup-mod-chips-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 100%;
  max-width: min(420px, 92vw);
  animation: startupSoftEnter 600ms ease 420ms both;
}

.startup-mod-chips-hint {
  font-size: var(--app-font-size-caption);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(23, 32, 51, 0.55);
}

.startup-mod-chips {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.startup-mod-chip {
  padding: var(--app-space-sm) var(--app-space-md);
  border-radius: 999px;
  font-size: 13px;
  color: #172033;
  background: rgba(255, 255, 255, 0.68);
  border: 1px solid rgba(255, 255, 255, 0.78);
  box-shadow:
    0 8px 20px rgba(15, 76, 129, 0.09),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(12px);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.startup-mod-status {
  text-align: center;
  font-size: var(--app-font-size-body);
  color: rgba(23, 32, 51, 0.66);
  min-height: 28px;
}

.mod-loading,
.mod-loaded,
.mod-error {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.54);
  border: 1px solid rgba(255, 255, 255, 0.72);
  box-shadow: 0 8px 20px rgba(15, 76, 129, 0.07);
  backdrop-filter: blur(12px);
  animation: fadeIn 300ms ease;
}

.mod-loading i {
  color: var(--app-accent, #1890ff);
}

.mod-loaded i {
  color: #36b35f;
}

.mod-error i {
  color: #ff4d4f;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes startupContentEnter {
  from {
    opacity: 0;
    transform: translateY(14px) scale(0.985);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes startupSoftEnter {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .startup-splash {
    transition-duration: 1ms;
  }

  .startup-logo-text,
  .startup-mod-title,
  .startup-progress-wrap,
  .startup-mod-chips-wrap,
  .mod-loading,
  .mod-loaded,
  .mod-error {
    animation: none;
  }

  .startup-logo-text,
  .startup-mod-title,
  .startup-progress-wrap {
    opacity: 1;
    transform: none;
  }
}
</style>
