<template>
  <div class="xcmax-dashboard-embed" :class="`is-${state}`">
    <iframe
      ref="frameRef"
      :key="frameKey"
      :title="title"
      :src="frameSrc"
      class="xcmax-dashboard-embed__frame"
      :class="{ 'is-hidden': state === 'error' }"
      referrerpolicy="no-referrer"
      @load="onFrameLoad"
      @error="onFrameError"
    />

    <div v-if="state === 'loading'" class="xcmax-dashboard-embed__status" role="status" aria-live="polite">
      <span class="xcmax-dashboard-embed__spinner" aria-hidden="true"></span>
      <strong>正在加载 {{ title }}</strong>
      <small>{{ retryCount ? `正在进行第 ${retryCount + 1} 次加载…` : '首次加载可能需要一些时间' }}</small>
    </div>

    <div v-else-if="state === 'error'" class="xcmax-dashboard-embed__status is-error" role="alert">
      <span class="xcmax-dashboard-embed__error-icon" aria-hidden="true">!</span>
      <strong>{{ title }}暂时未能载入</strong>
      <small>已自动重试。可以再次加载，或在新页面中打开完整看板。</small>
      <div class="xcmax-dashboard-embed__actions">
        <button type="button" @click="retry">重新加载</button>
        <a :href="src" target="_blank" rel="noopener noreferrer">新页面打开</a>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    src: string
    title?: string
  }>(),
  { title: 'XCMAX 全景' },
)

const MAX_AUTO_RETRIES = 1
const LOAD_WATCHDOG_MS = 40_000
const AUTO_RETRY_DELAY_MS = 1_200

const frameRef = ref<HTMLIFrameElement | null>(null)
const state = ref<'loading' | 'ready' | 'error'>('loading')
const retryCount = ref(0)
const reloadToken = ref(0)
let watchdogTimer: number | null = null
let retryTimer: number | null = null

const frameKey = computed(() => `${props.src}:${reloadToken.value}`)
const frameSrc = computed(() => {
  if (!reloadToken.value || typeof window === 'undefined') return props.src
  try {
    const parsed = new URL(props.src, window.location.href)
    parsed.searchParams.set('xcagi_embed_retry', String(reloadToken.value))
    return parsed.toString()
  } catch {
    const separator = props.src.includes('?') ? '&' : '?'
    return `${props.src}${separator}xcagi_embed_retry=${reloadToken.value}`
  }
})

function clearTimers() {
  if (watchdogTimer != null) window.clearTimeout(watchdogTimer)
  if (retryTimer != null) window.clearTimeout(retryTimer)
  watchdogTimer = null
  retryTimer = null
}

function armWatchdog() {
  if (watchdogTimer != null) window.clearTimeout(watchdogTimer)
  watchdogTimer = window.setTimeout(() => handleFailure(), LOAD_WATCHDOG_MS)
}

function startLoad() {
  clearTimers()
  state.value = 'loading'
  void nextTick(armWatchdog)
}

function handleFailure() {
  clearTimers()
  if (retryCount.value < MAX_AUTO_RETRIES) {
    retryTimer = window.setTimeout(() => {
      retryCount.value += 1
      reloadToken.value += 1
      startLoad()
    }, AUTO_RETRY_DELAY_MS)
    return
  }
  state.value = 'error'
}

function onFrameLoad() {
  if (state.value !== 'loading') return
  try {
    const actualUrl = frameRef.value?.contentWindow?.location?.href || frameRef.value?.contentDocument?.URL || ''
    if (!actualUrl || actualUrl === 'about:blank' || actualUrl.startsWith('chrome-error:')) {
      handleFailure()
      return
    }
  } catch {
    // dashboardBase() 保证同源；异常通常代表浏览器内部错误页。
    handleFailure()
    return
  }
  clearTimers()
  state.value = 'ready'
}

function onFrameError() {
  handleFailure()
}

function retry() {
  retryCount.value = 0
  reloadToken.value += 1
  startLoad()
}

watch(
  () => props.src,
  () => {
    retryCount.value = 0
    reloadToken.value += 1
    startLoad()
  },
  { immediate: true },
)

onBeforeUnmount(clearTimers)
</script>

<style scoped>
.xcmax-dashboard-embed {
  position: relative;
  width: 100%;
  min-height: min(72vh, 900px);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
  background: #f8fafc;
}
.xcmax-dashboard-embed__frame {
  width: 100%;
  height: min(72vh, 900px);
  border: 0;
  display: block;
  background: #fff;
}
.xcmax-dashboard-embed__frame.is-hidden {
  visibility: hidden;
}
.xcmax-dashboard-embed__status {
  position: absolute;
  inset: 0;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 10px;
  padding: 24px;
  color: #334155;
  text-align: center;
  background: linear-gradient(145deg, #f8fbff, #eef4fb);
}
.xcmax-dashboard-embed__status strong { font-size: 16px; }
.xcmax-dashboard-embed__status small { color: #64748b; line-height: 1.6; }
.xcmax-dashboard-embed__spinner {
  width: 30px;
  height: 30px;
  border: 3px solid #cbdcf1;
  border-top-color: #2576d9;
  border-radius: 50%;
  animation: dashboard-embed-spin 0.8s linear infinite;
}
.xcmax-dashboard-embed__status.is-error { background: linear-gradient(145deg, #fff, #f7f9fc); }
.xcmax-dashboard-embed__error-icon {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border-radius: 50%;
  color: #b42318;
  background: #fee4e2;
  font-weight: 800;
}
.xcmax-dashboard-embed__actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; margin-top: 4px; }
.xcmax-dashboard-embed__actions button,
.xcmax-dashboard-embed__actions a {
  padding: 8px 13px;
  border: 1px solid #b8c8dc;
  border-radius: 8px;
  color: #245f9f;
  background: #fff;
  font: inherit;
  font-size: 13px;
  text-decoration: none;
  cursor: pointer;
}
.xcmax-dashboard-embed__actions button:hover,
.xcmax-dashboard-embed__actions a:hover { border-color: #2576d9; }
@keyframes dashboard-embed-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .xcmax-dashboard-embed__spinner { animation-duration: 2s; }
}
</style>
