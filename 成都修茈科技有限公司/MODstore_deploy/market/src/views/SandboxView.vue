<template>
  <div class="sandbox-page">
    <div class="sandbox-toolbar">
      <div class="toolbar-left">
        <span class="toolbar-label">自动匹配</span>
        <input
          v-model="hostUrl"
          class="toolbar-input"
          placeholder="可留空；将扫本机常见 API 端口"
          @keydown.enter="discoverAndConnect"
        />
        <button class="btn btn-connect" :disabled="connecting" @click="discoverAndConnect">
          {{ connecting ? '扫端口中…' : '重新扫描' }}
        </button>
        <span v-if="statusText" class="status-chip" :class="statusClass">{{ statusText }}</span>
        <span v-if="connectError" class="status-chip status-err" role="alert">{{ connectError }}</span>
      </div>
      <div class="toolbar-right">
        <button class="btn btn-action" :disabled="!connected || pushing || !effectiveModId" @click="pushAndTest">
          {{ pushing ? '推送中...' : '推送当前 Mod 并测试' }}
        </button>
        <button class="btn btn-action" :disabled="!connected" @click="openFullscreen">全屏</button>
      </div>
    </div>

    <div v-if="connected && (!effectiveModId || isMixedContentBlocked || pushMessage)" class="sandbox-helper">
      <div class="helper-copy">
        <strong>{{ isMixedContentBlocked ? '已匹配，但浏览器拦截了画面' : '沙箱已匹配' }}</strong>
        <p v-if="isMixedContentBlocked">
          当前市场页是 HTTPS，但匹配到的宿主是 HTTP：{{ iframeSrc }}。请改用 HTTPS 宿主地址，或从本地 HTTP 页面打开沙箱。
        </p>
        <p v-else-if="!effectiveModId">
          当前地址没有携带 modId，所以不能自动推送“当前 Mod”。输入一个测试 Mod ID 后可直接推送并跳转测试。
        </p>
        <p v-if="pushMessage" class="helper-message">{{ pushMessage }}</p>
      </div>
      <div class="helper-actions">
        <input
          v-model="manualModId"
          class="toolbar-input helper-input"
          placeholder="测试 Mod ID，例如 example-mod"
          @keydown.enter="pushAndTest"
        />
        <button class="btn btn-action" :disabled="pushing || !effectiveModId" @click="pushAndTest">
          {{ pushing ? '推送中...' : '推送测试 Mod' }}
        </button>
        <button class="btn" :disabled="!hostUrl" @click="openHostInNewTab">打开宿主页</button>
      </div>
    </div>

    <div v-if="connected && !isMixedContentBlocked" class="sandbox-iframe-wrap">
      <iframe
        ref="iframeRef"
        :src="iframeSrc"
        class="sandbox-iframe"
        allow="clipboard-read; clipboard-write"
      />
    </div>
    <div v-else-if="connected" class="sandbox-placeholder">
      <div class="placeholder-icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
          <line x1="8" y1="21" x2="16" y2="21" />
          <line x1="12" y1="17" x2="12" y2="21" />
        </svg>
      </div>
      <p class="placeholder-text">画面被浏览器安全策略拦截</p>
      <p class="placeholder-hint">HTTPS 市场页不能嵌入 HTTP 宿主 iframe。请在上方填入 HTTPS 宿主地址后重新扫描。</p>
    </div>
    <div v-else class="sandbox-placeholder">
      <div class="placeholder-icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
          <line x1="8" y1="21" x2="16" y2="21" />
          <line x1="12" y1="17" x2="12" y2="21" />
        </svg>
      </div>
      <p class="placeholder-text">正在本机与局域网自动扫描常见 API 端口并匹配 XCAGI / FHD</p>
      <p class="placeholder-hint">
        依次探测多端口（如 5000–5002、5173–5176、8000 等）；命中后写入上方；也可手动填根地址后回车或点「重新扫描」
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { sandboxApi } from '../application/sandboxApi'
import { ApiError } from '../infrastructure/http/client'

const route = useRoute()

/** 上次成功连上的宿主 API 根，供下次优先探测 */
const SANDBOX_HOST_STORAGE = 'modstore_sandbox_last_host'
/** 线上默认优先使用同源沙盒，不再先命中 http://域名:4173 导致 HTTPS 混合内容拦截 */
const DEFAULT_SANDBOX_HOST_PATH = import.meta.env.VITE_SANDBOX_HOST_PATH || '/sandbox'

const hostUrl = ref('')
const connected = ref(false)
const connecting = ref(false)
const connectError = ref('')
const probeProgress = ref('')
const pushing = ref(false)
const hostInfo = ref(null)
const iframeRef = ref(null)
const manualModId = ref('')
const pushMessage = ref('')

const effectiveModId = computed(() => {
  const raw = route.query.modId || route.params.modId || manualModId.value
  return String(raw || '').trim()
})

const statusText = computed(() => {
  if (connected.value) return '已匹配'
  if (connecting.value) {
    return probeProgress.value ? `扫端口 (${probeProgress.value})` : '扫端口中'
  }
  return ''
})

const statusClass = computed(() => {
  return connected.value ? 'status-ok' : 'status-pending'
})

const iframeSrc = computed(() => {
  if (!connected.value || !hostUrl.value) return ''
  const base = hostUrl.value.replace(/\/+$/, '')
  return `${base}/?sandbox=1`
})

const isMixedContentBlocked = computed(() => {
  if (!connected.value || !hostUrl.value) return false
  try {
    const url = new URL(hostUrl.value)
    return window.location.protocol === 'https:' && url.protocol === 'http:' && !isLoopbackHost(url.hostname)
  } catch {
    return window.location.protocol === 'https:' && hostUrl.value.startsWith('http://') && !isLoopbackOrigin(hostUrl.value)
  }
})

function formatConnectFailure(e) {
  if (e instanceof ApiError) return e.message || `请求失败（${e.status}）`
  if (e && typeof e === 'object' && 'message' in e && typeof e.message === 'string') return e.message
  return String(e)
}

/** 规范为「协议 + host」，供 /api/health 探测 */
function normalizeHostOrigin(raw) {
  const t = String(raw || '').trim()
  if (!t) return ''
  if (t.startsWith('/')) {
    return `${window.location.origin}${t}`.replace(/\/+$/, '')
  }
  try {
    const withProto = /^\w+:\/\//.test(t) ? t : `http://${t}`
    const u = new URL(withProto)
    return `${u.protocol}//${u.host}${u.pathname === '/' ? '' : u.pathname}`.replace(/\/+$/, '')
  } catch {
    return t.replace(/\/+$/, '')
  }
}

function isLoopbackHost(hostname) {
  const h = String(hostname || '').trim().toLowerCase()
  return h === 'localhost' || h === '127.0.0.1' || h === '[::1]' || h === '::1'
}

function isLoopbackOrigin(raw) {
  try {
    return isLoopbackHost(new URL(normalizeHostOrigin(raw)).hostname)
  } catch {
    return false
  }
}

async function probeFromBrowser(url) {
  const base = normalizeHostOrigin(url)
  if (!base) return null
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 1200)
  try {
    const sameOrigin = new URL(base).origin === window.location.origin
    // 本机端口必须从用户浏览器探测；线上后端访问 localhost 只会访问服务器自己。
    const resp = await fetch(`${base}/api/health`, {
      method: 'GET',
      mode: sameOrigin ? 'same-origin' : 'no-cors',
      cache: 'no-store',
      signal: controller.signal,
    })
    if (sameOrigin && !resp.ok) return null
    return { ok: true, host_url: base, source: 'browser-local' }
  } catch (_) {
    return null
  } finally {
    window.clearTimeout(timer)
  }
}

function shouldProbeFromBrowser(url) {
  if (isLoopbackOrigin(url)) return true
  try {
    return new URL(normalizeHostOrigin(url)).origin === window.location.origin
  } catch {
    return false
  }
}

/**
 * 本机 / 局域网常见 XCAGI FastAPI 与联调端口；线上 HTTPS 优先用 /sandbox，不再探测裸 HTTP 4173。
 * 每项为端口号，将拼成 http://127.0.0.1:{port} 与 http://localhost:{port}，并对当前页 hostname 复用。
 */
const LOCAL_PROBE_PORTS = [
  5000, 5001, 5002, 5003,
  5173, 5174, 5175, 5176, 5177,
  3000, 8080, 8888,
  8000, 8001,
]

function addHostPortVariants(add, hostname, ports, includeHttps, includeHttp = true) {
  const h = String(hostname || '').trim()
  if (!h) return
  for (const p of ports) {
    if (includeHttps) add(`https://${h}:${p}`)
    if (includeHttp) add(`http://${h}:${p}`)
  }
}

/** 合并去重：URL 参数 → 同源 /sandbox → 输入框 → 上次成功 → 本机端口 → 当前页同机多端口扫描 */
function buildDiscoveryCandidates() {
  const seen = new Set()
  const out = []
  const add = (raw) => {
    const n = normalizeHostOrigin(raw)
    if (!n || seen.has(n)) return
    seen.add(n)
    out.push(n)
  }

  const q = route.query.host
  if (q) add(String(q))

  add(DEFAULT_SANDBOX_HOST_PATH)

  add(hostUrl.value)

  try {
    const s = localStorage.getItem(SANDBOX_HOST_STORAGE)
    if (s) add(s)
  } catch (_) {
    /* ignore */
  }

  try {
    const { hostname, protocol } = window.location
    const p = String(window.location.port || '').trim()
    if (isLoopbackHost(hostname) && p && /^\d+$/.test(p) && p !== '80' && p !== '443') {
      add(`${protocol}//${hostname}:${p}`)
    }
  } catch (_) {
    /* ignore */
  }

  addHostPortVariants(add, '127.0.0.1', LOCAL_PROBE_PORTS, false)
  addHostPortVariants(add, 'localhost', LOCAL_PROBE_PORTS, false)

  try {
    const { hostname, protocol } = window.location
    if (hostname && !isLoopbackHost(hostname)) {
      const isHttpsPage = protocol === 'https:'
      addHostPortVariants(add, hostname, LOCAL_PROBE_PORTS, isHttpsPage, !isHttpsPage)
    }
  } catch (_) {
    /* ignore */
  }

  return out
}

/** 依次尝试候选地址，成功则写入输入框并记住 */
async function discoverAndConnect() {
  if (connecting.value) return
  connecting.value = true
  connected.value = false
  hostInfo.value = null
  connectError.value = ''
  pushMessage.value = ''
  probeProgress.value = ''

  const list = buildDiscoveryCandidates()
  if (!list.length) {
    connectError.value = '请填写宿主 API 根地址（例如 http://127.0.0.1:5000）'
    connecting.value = false
    return
  }

  let lastApiError = null

  for (let i = 0; i < list.length; i++) {
    const url = list[i]
    hostUrl.value = url
    probeProgress.value = `${i + 1}/${list.length}`
    try {
      const result = shouldProbeFromBrowser(url)
        ? await probeFromBrowser(url)
        : await sandboxApi.connectHost(url)
      if (result && result.ok === true) {
        connected.value = true
        hostInfo.value = result
        try {
          localStorage.setItem(SANDBOX_HOST_STORAGE, url)
        } catch (_) {
          /* ignore */
        }
        probeProgress.value = ''
        connecting.value = false
        return
      }
    } catch (e) {
      lastApiError = e
    }
  }

  probeProgress.value = ''
  if (lastApiError) {
    connectError.value = formatConnectFailure(lastApiError)
  } else {
    connectError.value =
      '未发现可连宿主（已试常用地址与当前页同机）。请确认 XCAGI 已启动后点「重新探测」，或手动填写 API 根地址。'
  }
  console.warn('[Sandbox] 探测结束，未找到可用宿主')
  connecting.value = false
}

async function pushAndTest() {
  if (!connected.value || pushing.value) return
  const modId = effectiveModId.value
  if (!modId) {
    pushMessage.value = '请先输入要测试的 Mod ID'
    return
  }
  pushing.value = true
  pushMessage.value = ''
  try {
    const result = await sandboxApi.pushAndTest(hostUrl.value, String(modId))
    if (result.ok) {
      if (iframeRef.value) {
        iframeRef.value.contentWindow?.postMessage(
          { type: 'sandbox:navigate', path: `/mod/${modId}` },
          '*'
        )
      }
      pushMessage.value = `已推送 ${modId}，正在宿主中打开测试页`
    } else {
      pushMessage.value = String(result.error || '推送失败，请检查 Mod ID 或宿主状态')
    }
  } catch (e) {
    console.warn('[Sandbox] 推送失败:', e)
    pushMessage.value = formatConnectFailure(e)
  } finally {
    pushing.value = false
  }
}

function openHostInNewTab() {
  if (!iframeSrc.value) return
  window.open(iframeSrc.value, '_blank', 'noopener,noreferrer')
}

function openFullscreen() {
  if (!iframeRef.value) return
  const el = iframeRef.value
  if (el.requestFullscreen) el.requestFullscreen()
  else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen()
}

function shouldAutoPush() {
  const raw = String(route.query.autoPush || '').trim().toLowerCase()
  return raw === '1' || raw === 'true' || raw === 'yes'
}

let messageHandler = null

onMounted(() => {
  messageHandler = (e) => {
    if (e.data?.type === 'sandbox:ready') {
      console.log('[Sandbox] FHD 宿主已就绪')
    }
  }
  window.addEventListener('message', messageHandler)

  void discoverAndConnect().then(() => {
    if (connected.value && effectiveModId.value && shouldAutoPush()) {
      void pushAndTest()
    }
  })
})

onBeforeUnmount(() => {
  if (messageHandler) {
    window.removeEventListener('message', messageHandler)
    messageHandler = null
  }
})
</script>

<style scoped>
.sandbox-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.sandbox-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 16px;
  background: var(--color-bg-elevated, #1a1a1a);
  border-bottom: 0.5px solid var(--color-border-subtle, rgba(255, 255, 255, 0.1));
  flex-shrink: 0;
  flex-wrap: wrap;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-label {
  font-size: 0.85rem;
  color: var(--color-text-muted, rgba(255, 255, 255, 0.55));
  white-space: nowrap;
}

.toolbar-input {
  width: 260px;
  padding: 6px 10px;
  border: 0.5px solid var(--color-border-subtle, rgba(255, 255, 255, 0.15));
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.03);
  color: var(--color-text-primary, #fff);
  font-size: 0.85rem;
  outline: none;
  transition: border-color 0.2s;
}

.toolbar-input:focus {
  border-color: rgba(255, 255, 255, 0.3);
}

.toolbar-input::placeholder {
  color: rgba(255, 255, 255, 0.3);
}

.btn {
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  border: 0.5px solid rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.06);
  color: var(--color-text-primary, #fff);
  transition: all 0.2s;
  white-space: nowrap;
}

.btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
}

.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-connect {
  background: rgba(96, 165, 250, 0.15);
  color: #60a5fa;
  border-color: rgba(96, 165, 250, 0.3);
}

.btn-connect:hover:not(:disabled) {
  background: rgba(96, 165, 250, 0.25);
}

.btn-action {
  background: rgba(74, 222, 128, 0.12);
  color: #4ade80;
  border-color: rgba(74, 222, 128, 0.25);
}

.btn-action:hover:not(:disabled) {
  background: rgba(74, 222, 128, 0.2);
}

.status-chip {
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 600;
}

.status-ok {
  color: #4ade80;
  background: rgba(74, 222, 128, 0.1);
}

.status-pending {
  color: #fbbf24;
  background: rgba(251, 191, 36, 0.1);
}

.status-err {
  color: #f87171;
  background: rgba(248, 113, 113, 0.12);
  max-width: min(520px, 100%);
  white-space: normal;
  line-height: 1.35;
}

.sandbox-iframe-wrap {
  flex: 1 1 0%;
  min-height: 0;
  position: relative;
}

.sandbox-helper {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  background: rgba(96, 165, 250, 0.08);
  border-bottom: 0.5px solid rgba(96, 165, 250, 0.18);
  color: var(--color-text-primary, #fff);
  flex-wrap: wrap;
}

.helper-copy {
  min-width: 260px;
  flex: 1 1 360px;
}

.helper-copy strong {
  display: block;
  margin-bottom: 4px;
  font-size: 0.9rem;
}

.helper-copy p {
  margin: 0;
  color: var(--color-text-muted, rgba(255, 255, 255, 0.6));
  font-size: 0.82rem;
  line-height: 1.45;
}

.helper-message {
  margin-top: 4px !important;
  color: #fbbf24 !important;
}

.helper-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.helper-input {
  width: 220px;
}

.sandbox-iframe {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
}

.sandbox-placeholder {
  flex: 1 1 0%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--color-text-muted, rgba(255, 255, 255, 0.4));
}

.placeholder-icon {
  opacity: 0.4;
}

.placeholder-text {
  font-size: 1rem;
  font-weight: 500;
}

.placeholder-hint {
  font-size: 0.85rem;
  opacity: 0.6;
}

@media (max-width: 768px) {
  .sandbox-toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
  }
  .toolbar-left,
  .toolbar-right {
    flex-wrap: wrap;
  }
  .toolbar-input {
    width: 100%;
  }
}

html[data-workbench-theme='light'] .sandbox-page {
  background: #f5f5f7;
}

html[data-workbench-theme='light'] .sandbox-toolbar {
  background: #ffffff;
  border-bottom-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .toolbar-label {
  color: #86868b;
}

html[data-workbench-theme='light'] .toolbar-input {
  border-color: rgba(0, 0, 0, 0.1);
  background: rgba(0, 0, 0, 0.03);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .toolbar-input:focus {
  border-color: #0071e3;
}

html[data-workbench-theme='light'] .toolbar-input::placeholder {
  color: rgba(0, 0, 0, 0.25);
}

html[data-workbench-theme='light'] .btn {
  border-color: rgba(0, 0, 0, 0.1);
  background: rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .btn:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.07);
}

html[data-workbench-theme='light'] .btn-connect {
  background: rgba(0, 113, 227, 0.08);
  color: #0071e3;
  border-color: rgba(0, 113, 227, 0.2);
}

html[data-workbench-theme='light'] .btn-connect:hover:not(:disabled) {
  background: rgba(0, 113, 227, 0.14);
}

html[data-workbench-theme='light'] .btn-action {
  background: rgba(52, 199, 89, 0.08);
  color: #34c759;
  border-color: rgba(52, 199, 89, 0.2);
}

html[data-workbench-theme='light'] .btn-action:hover:not(:disabled) {
  background: rgba(52, 199, 89, 0.14);
}

html[data-workbench-theme='light'] .status-ok {
  color: #34c759;
  background: rgba(52, 199, 89, 0.08);
}

html[data-workbench-theme='light'] .status-pending {
  color: #d97706;
  background: rgba(217, 119, 6, 0.08);
}

html[data-workbench-theme='light'] .status-err {
  color: #e53935;
  background: rgba(229, 57, 53, 0.08);
}

html[data-workbench-theme='light'] .sandbox-helper {
  background: rgba(0, 113, 227, 0.06);
  border-bottom-color: rgba(0, 113, 227, 0.12);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .helper-copy p {
  color: #86868b;
}

html[data-workbench-theme='light'] .helper-message {
  color: #d97706 !important;
}

html[data-workbench-theme='light'] .sandbox-placeholder {
  color: #86868b;
}

html[data-workbench-theme='light'] .placeholder-icon {
  opacity: 0.3;
}

html[data-workbench-theme='light'] .placeholder-text {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .placeholder-hint {
  color: #86868b;
  opacity: 1;
}
</style>
