<template>
  <div class="aiopen-shell">
    <header class="aiopen-header">
      <button class="aiopen-back" type="button" @click="$emit('back')">← 返回</button>
      <div class="aiopen-header-brand">AIOPEN 开放智控</div>
      <span class="aiopen-header-spacer" aria-hidden="true"></span>
    </header>

    <div class="aiopen-scroll">
    <div class="aiopen-stage">

    <div class="aiopen-hero" :class="`aiopen-hero--${readyStatus}`">
      <div class="aiopen-hero-top">
        <div class="aiopen-hero-badge">AI 工具 · 开放智控</div>
        <div class="aiopen-hero-icon-wrap">
          <div class="aiopen-hero-icon" aria-hidden="true">
            <svg v-if="readyStatus === 'ready'" viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 13l4 4L19 7"/></svg>
            <svg v-else viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3v3M12 18v3M3 12h3M18 12h3"/><circle cx="12" cy="12" r="4"/><path d="M8 8l2 2M14 14l2 2M14 8l2-2M8 14l2 2"/></svg>
          </div>
          <span v-if="readyStatus === 'ready'" class="aiopen-live-dot"></span>
        </div>
        <h1 class="aiopen-hero-title">AIOPEN</h1>
        <p class="aiopen-hero-tagline">让外部 AI 像助手一样，帮你操作本软件</p>
      </div>

      <ul class="aiopen-features">
        <li v-for="f in featureIntro" :key="f.title">
          <span class="aiopen-feature-icon" aria-hidden="true">{{ f.icon }}</span>
          <div>
            <strong>{{ f.title }}</strong>
            <span>{{ f.desc }}</span>
          </div>
        </li>
      </ul>

      <div class="aiopen-flow">
        <span v-for="(step, i) in flowSteps" :key="step" class="aiopen-flow-item" :class="{ done: flowDone[i] }">
          <em>{{ i + 1 }}</em>{{ step }}
        </span>
      </div>

      <p class="aiopen-hero-status">{{ statusText }}</p>
      <p v-if="mcpHealthText" class="aiopen-mcp-health" :class="{ ok: mcpHealthy }">{{ mcpHealthText }}</p>
      <p v-if="panelError" class="aiopen-hero-warn">{{ panelError }}</p>

      <button
        class="aiopen-primary-btn"
        type="button"
        :disabled="setupRunning || readyStatus === 'ready'"
        @click="quickSetup"
      >
        {{ setupRunning ? '开启中…' : primaryBtnLabel }}
      </button>

      <div class="aiopen-oneline">
        <p class="aiopen-oneline-label">发给其他 AI 助手</p>
        <p class="aiopen-oneline-preview">{{ oneLinerPreview }}</p>
        <div class="aiopen-oneline-actions">
          <button class="aiopen-oneline-btn" type="button" @click="copyOneLiner">
            复制一句话
          </button>
          <button class="aiopen-oneline-btn aiopen-oneline-btn--ghost" type="button" @click="copyAiAssistantPrompt">
            完整配置
          </button>
        </div>
      </div>

      <div class="aiopen-client-section">
        <p class="aiopen-client-title">选择 AI 软件接入 <span class="aiopen-client-sub">可同时配置多个</span></p>
        <div class="aiopen-client-grid">
          <button
            v-for="client in aiClients"
            :key="client.id"
            type="button"
            class="aiopen-client-btn"
            :class="{ done: installedClientIds.includes(client.id) }"
            @click="handleClientClick(client)"
          >
            <span class="aiopen-client-icon" aria-hidden="true">{{ client.icon }}</span>
            <span class="aiopen-client-name">{{ client.name }}</span>
            <span class="aiopen-client-action">{{ clientActionLabel(client) }}</span>
          </button>
        </div>
      </div>

      <details v-if="friendlyTools.length" class="aiopen-tools-preview">
        <summary>MCP 工具 · {{ friendlyTools.length }} 个</summary>
        <ul>
          <li v-for="tool in friendlyTools" :key="tool.name">
            <strong>{{ tool.label }}</strong>
            <span>{{ tool.desc }}</span>
          </li>
        </ul>
      </details>

      <p v-if="accessResult" class="aiopen-toast">{{ accessResult }}</p>
    </div>

    <details class="aiopen-more">
      <summary>更多设置</summary>
      <div class="aiopen-more-body">
        <button class="aiopen-link-btn" type="button" @click="loadPanel">刷新状态</button>
        <p v-if="!panelAvailable" class="aiopen-offline-hint">离线模式：可先配置 AI 软件；开启远程操控需后端在线</p>

        <label class="aiopen-switch-row">
          <input type="checkbox" :checked="remoteControlEnabled" @change="toggleRemoteControl($event)">
          <span>允许 AI 远程操控</span>
        </label>
        <label class="aiopen-switch-row">
          <input type="checkbox" :checked="cursorEnabled" @change="toggleScreenSession($event)">
          <span>本页待命{{ cursorConnected ? ' · 已连接' : '' }}</span>
        </label>

        <div class="aiopen-more-actions">
          <button class="btn btn-secondary btn-sm" type="button" @click="copyClientConfig(selectedClientId)">复制 MCP JSON</button>
          <button class="btn btn-secondary btn-sm" type="button" @click="copyGuideUrl">复制说明链接</button>
          <button v-if="!activeKey" class="btn btn-secondary btn-sm" type="button" @click="createKey">获取口令</button>
        </div>

        <div class="aiopen-client-picker">
          <span class="aiopen-client-picker-label">配置预览</span>
          <select v-model="selectedClientId" class="aiopen-select aiopen-client-select">
            <option v-for="client in aiClients" :key="client.id" :value="client.id">{{ client.name }}</option>
          </select>
          <p class="aiopen-client-picker-hint">{{ selectedClient?.configPath }} · {{ selectedClient?.hint }}</p>
        </div>

        <details class="aiopen-nested">
          <summary>开发者 / 高级</summary>
          <div class="aiopen-advanced-body">
            <pre class="aiopen-pre">{{ selectedClientConfigSnippet }}</pre>
            <div class="aiopen-endpoint-row">
              <code class="aiopen-endpoint-code">{{ mcpUrl }}</code>
              <button class="btn btn-secondary btn-sm" type="button" @click="copyText(mcpUrl)">MCP</button>
            </div>
            <div class="aiopen-tools">
              <div v-for="tool in friendlyTools" :key="tool.name" class="aiopen-tool-item">
                <span>{{ tool.label }}</span>
                <span>{{ tool.desc }}</span>
              </div>
            </div>
            <div class="aiopen-route-list">
              <label v-for="route in routes" :key="route.path" class="aiopen-route-item">
                <input type="checkbox" :checked="route.enabled" @change="toggleWhitelist(route.path, $event)">
                <code>{{ route.path }}</code>
              </label>
            </div>
            <label class="aiopen-switch-row">
              <input type="checkbox" :checked="wechatOpen" @change="toggleWechat($event)">
              <span>微信开放权限</span>
            </label>
            <div class="aiopen-row">
              <input v-model="openclawBase" class="aiopen-input" placeholder="OpenClaw 地址">
              <button class="btn btn-secondary btn-sm" type="button" @click="saveOpenclawBase">保存</button>
            </div>
            <div class="aiopen-row">
              <input v-model="openclawMessage" class="aiopen-input" placeholder="测试消息">
              <button class="btn btn-primary btn-sm" type="button" :disabled="openclawSending" @click="sendToOpenclaw">发送</button>
            </div>
            <div class="aiopen-result">{{ openclawResult }}</div>
            <div class="aiopen-row aiopen-row-auth">
              <select v-model="openclawWsAuthMode" class="aiopen-select">
                <option value="token">token</option>
                <option value="password">password</option>
              </select>
              <input v-model="openclawGatewayToken" class="aiopen-input" placeholder="Token/密码">
            </div>
            <div class="aiopen-row">
              <input v-model="openclawWsUrl" class="aiopen-input" placeholder="ws://localhost:28789/ws">
              <button class="btn btn-secondary btn-sm" type="button" :disabled="wsConnected || wsConnecting" @click="connectOpenclawWs">WS</button>
            </div>
            <div class="aiopen-result">{{ wsStatusText }}</div>
          </div>
        </details>
      </div>
    </details>
    </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { safeJsonRequest } from '@/utils/safeJsonRequest'
import { getApiBase } from '@/utils/apiBase'
import { useAiOpenCursor } from '@/composables/useAiOpenCursor'
import {
  AIOPEN_MCP_SERVER_NAME,
  buildAiopenClientInstalls,
  buildAiAssistantSetupPrompt,
  buildAiopenOneLiner,
  markAiopenClientInstalled,
  readAiopenInstalledClients,
  resolveAiopenBackendBase,
  unmarkAiopenClientInstalled,
} from '@/utils/aiopenMcpInstall'

defineEmits(['back'])

const {
  enabled: cursorEnabled,
  connected: cursorConnected,
  setEnabled: setCursorEnabled,
} = useAiOpenCursor()

const TOOL_LABELS = {
  api_catalog: { label: '查看接口', desc: '列出可调用的业务接口' },
  api_call: { label: '调用接口', desc: '代你请求订单、产品等业务数据' },
  chat: { label: '对话', desc: '和 XCAGI AI 助手聊天' },
  ui_sessions: { label: '查看屏幕', desc: '有哪些浏览器正在待命' },
  ui_snapshot: { label: '看页面', desc: '读取当前页面上的按钮和输入框' },
  ui_navigate: { label: '跳转', desc: '打开指定菜单或页面' },
  ui_click: { label: '点击', desc: '用虚拟光标点击按钮' },
  ui_type: { label: '输入', desc: '在输入框里打字' },
  ui_scroll: { label: '滚动', desc: '滚动页面找到内容' },
}

const wechatOpen = ref(false)
const routes = ref([])
const remoteControlEnabled = ref(false)
const keys = ref([])
const newKey = ref('')
const accessResult = ref('')
const panelError = ref('')
const panelAvailable = ref(true)
const manifestTools = ref([])
const setupRunning = ref(false)
const installBundle = ref(null)
const mcpHealthy = ref(false)
const mcpHealthText = ref('')
const installedClientIds = ref([])
const selectedClientId = ref('cursor')
const stdioScriptPath = ref('')
const oneLinerCopied = ref(false)

const openclawBase = ref('http://localhost:28789')
const openclawMessage = ref('你好')
const openclawSending = ref(false)
const openclawResult = ref('')

const apiOrigin = computed(() => {
  const base = getApiBase()
  if (base) return base
  return typeof window !== 'undefined' ? window.location.origin : ''
})

const backendOrigin = computed(() =>
  resolveAiopenBackendBase(apiOrigin.value, {
    envApiBase: String(import.meta.env.VITE_API_BASE || ''),
    mcpUrl: installBundle.value?.mcp_url || installBundle.value?.methods?.url?.config?.url,
  })
)

const mcpUrl = computed(() => `${backendOrigin.value}/api/aiopen/mcp`)
const guideUrl = computed(() => `${backendOrigin.value}/api/aiopen/guide?format=markdown`)

const activeKey = computed(() => newKey.value || '')
const hasConnectConfig = computed(() => Boolean(activeKey.value) || keys.value.length > 0)

const aiAssistantPrompt = computed(() =>
  buildAiAssistantSetupPrompt({
    backendBase: backendOrigin.value,
    apiKey: activeKey.value,
    clientId: selectedClientId.value,
    guideUrl: guideUrl.value,
  })
)

const oneLinerText = computed(() => buildAiopenOneLiner(backendOrigin.value, activeKey.value))

const oneLinerPreview = computed(() => {
  const t = oneLinerText.value
  return t.length > 72 ? `${t.slice(0, 72)}…` : t
})

const readyStatus = computed(() => {
  if (remoteControlEnabled.value && cursorConnected.value) return 'ready'
  if (remoteControlEnabled.value || cursorEnabled.value) return 'partial'
  return 'off'
})

const featureIntro = [
  { icon: '◎', title: '虚拟光标', desc: 'AI 看见页面，帮你点击和输入' },
  { icon: '⚡', title: '业务调用', desc: '查订单、发消息、调接口' },
  { icon: '🔗', title: '开放接入', desc: 'Cursor / Claude / VS Code 等均可配置' },
]

const flowSteps = ['一键开启', '复制一句话', '说「帮我操作」']

const anyClientInstalled = computed(() => installedClientIds.value.length > 0)

const flowDone = computed(() => [
  remoteControlEnabled.value || cursorEnabled.value,
  anyClientInstalled.value || hasConnectConfig.value || oneLinerCopied.value,
  readyStatus.value === 'ready',
])

const statusText = computed(() => {
  if (readyStatus.value === 'ready') return '已就绪 · 右下角显示连接徽标'
  if (readyStatus.value === 'partial') return '连接中 · 请保持本页打开'
  return '两步即可：开启 → 选择 AI 软件安装'
})

const primaryBtnLabel = computed(() => {
  if (setupRunning.value) return '开启中…'
  return readyStatus.value === 'ready' ? '已开启' : '一键开启'
})

const friendlyTools = computed(() =>
  manifestTools.value.map((t) => ({
    name: t.name,
    label: TOOL_LABELS[t.name]?.label || t.name,
    desc: TOOL_LABELS[t.name]?.desc || t.description,
  }))
)

const aiClients = computed(() =>
  buildAiopenClientInstalls(backendOrigin.value, activeKey.value, {
    stdioScriptPath: stdioScriptPath.value || undefined,
  })
)

const selectedClient = computed(() => aiClients.value.find((c) => c.id === selectedClientId.value) || aiClients.value[0])

const selectedClientConfigSnippet = computed(() => selectedClient.value?.mcpJson || '')

const refreshInstalledClients = () => {
  installedClientIds.value = readAiopenInstalledClients()
}

const loadInstallBundle = async () => {
  const qs = activeKey.value ? `?key=${encodeURIComponent(activeKey.value)}` : ''
  try {
    const result = await safeJsonRequest(`/api/aiopen/install${qs}`)
    if (result.ok && result.data?.success) {
      installBundle.value = result.data
      stdioScriptPath.value = String(result.data?.methods?.stdio?.script_path || '')
      return
    }
  } catch {
    /* install 端点可选 */
  }
  installBundle.value = {
    success: true,
    tool_count: manifestTools.value.length,
    server_name: AIOPEN_MCP_SERVER_NAME,
    clients: aiClients.value,
  }
}

const probeMcpHealth = async () => {
  mcpHealthText.value = ''
  mcpHealthy.value = false
  try {
    const manifest = await safeJsonRequest('/api/aiopen/manifest')
    if (manifest.ok && manifest.data?.success && manifest.data?.name === 'AIOPEN') {
      const count = Array.isArray(manifest.data.tools) ? manifest.data.tools.length : 9
      mcpHealthy.value = true
      mcpHealthText.value = `MCP 服务正常 · ${count} 个工具已注册`
      return
    }
    const probe = await safeJsonRequest('/api/aiopen/mcp')
    if (probe.ok && probe.data?.success && probe.data?.server === 'AIOPEN') {
      mcpHealthy.value = true
      mcpHealthText.value = `MCP 服务正常 · ${probe.data.tool_count || 9} 个工具已注册`
      return
    }
    const status = manifest.status || probe.status || 0
    if (status === 403) {
      mcpHealthText.value = 'MCP 自检被拦截（403）· 请刷新页面或重启后端'
    } else {
      mcpHealthText.value = status ? `MCP 服务未响应（HTTP ${status}）` : 'MCP 自检失败'
    }
  } catch {
    mcpHealthText.value = 'MCP 自检失败，请确认后端已启动（:5100）'
  }
}

const clientActionLabel = (client) =>
  installedClientIds.value.includes(client.id) ? '再次点击取消' : client.installLabel

const resetClientSelection = (client) => {
  unmarkAiopenClientInstalled(client.id)
  refreshInstalledClients()
  if (selectedClientId.value === client.id) {
    selectedClientId.value = 'cursor'
  }
  accessResult.value = `${client.name} 已取消 · 可再次点击配置`
}

const handleClientClick = async (client) => {
  if (!client) return
  if (installedClientIds.value.includes(client.id)) {
    resetClientSelection(client)
    return
  }
  await installForClient(client)
}

const installForClient = async (client) => {
  if (!client) return
  if (!hasConnectConfig.value && panelAvailable.value) await createKey()
  await loadInstallBundle()
  selectedClientId.value = client.id

  if (client.installMode === 'deeplink' && client.installUrl) {
    window.location.href = client.installUrl
    window.setTimeout(() => {
      if (document.visibilityState === 'visible' && client.installFallbackUrl) {
        window.open(client.installFallbackUrl, '_blank', 'noopener,noreferrer')
      }
    }, 1200)
    markAiopenClientInstalled(client.id)
    refreshInstalledClients()
    accessResult.value = `${client.name}：已打开安装链接；若未跳转请允许弹窗或复制 JSON`
    return
  }

  if (client.installMode === 'vscode' && client.installUrl) {
    window.location.href = client.installUrl
    markAiopenClientInstalled(client.id)
    refreshInstalledClients()
    accessResult.value = `${client.name}：已打开 VS Code 安装；未跳转请复制 JSON 手动添加`
    return
  }

  await copyText(client.mcpJson)
  markAiopenClientInstalled(client.id)
  refreshInstalledClients()
  accessResult.value = `${client.name} 配置已复制 · 粘贴到 ${client.configPath}`
}

const copyClientConfig = (clientId) => {
  const client = aiClients.value.find((c) => c.id === clientId) || selectedClient.value
  if (client) copyText(client.mcpJson)
}

const formatPanelError = (result) => {
  if (result.status === 404) return '后端未就绪（路由未生效，请重启服务）'
  if (result.status === 502 || result.status === 500) {
    return '后端未启动（:5100）· 下方 AI 配置仍可用，启动后点刷新'
  }
  if (result.message?.includes('未返回JSON')) {
    return '后端未启动（:5100）· 下方 AI 配置仍可用，启动后点刷新'
  }
  return result.message || '无法连接后端'
}

const loadPanel = async () => {
  panelError.value = ''
  accessResult.value = ''
  try {
    const result = await safeJsonRequest('/api/aiopen/panel')
    if (result.ok && result.data?.success) {
      panelAvailable.value = true
      wechatOpen.value = Boolean(result.data.wechat_open)
      routes.value = Array.isArray(result.data.routes) ? result.data.routes : []
      openclawBase.value = String(result.data.openclaw_base || 'http://localhost:28789')
      remoteControlEnabled.value = Boolean(result.data.remote_control_enabled)
      keys.value = Array.isArray(result.data.keys) ? result.data.keys : []
    } else {
      panelAvailable.value = false
      panelError.value = formatPanelError(result)
      routes.value = []
    }
  } catch {
    panelAvailable.value = false
    panelError.value = '无法连接后端（:5100）· 下方 AI 配置仍可用'
    routes.value = []
  }
  try {
    const mf = await safeJsonRequest('/api/aiopen/manifest')
    if (mf.ok && mf.data?.success) {
      manifestTools.value = Array.isArray(mf.data.tools) ? mf.data.tools : []
    }
  } catch {
    manifestTools.value = Object.keys(TOOL_LABELS).map((name) => ({
      name,
      description: TOOL_LABELS[name].desc,
    }))
  }
  await loadInstallBundle()
  await probeMcpHealth()
}

const copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
    accessResult.value = '已复制'
  } catch {
    accessResult.value = '复制失败，请手动复制'
  }
}

const copyOneLiner = async () => {
  if (!hasConnectConfig.value && panelAvailable.value) await createKey()
  await copyText(oneLinerText.value)
  try { localStorage.setItem('aiopen_oneliner_copied', '1') } catch { /* ignore */ }
  oneLinerCopied.value = true
  markAiopenClientInstalled('generic')
  refreshInstalledClients()
  accessResult.value = '一句话已复制 · 粘贴到 ChatGPT / Claude / Kimi 对话框'
}

const copyAiAssistantPrompt = async () => {
  if (!hasConnectConfig.value && panelAvailable.value) await createKey()
  await loadInstallBundle()
  await copyText(aiAssistantPrompt.value)
  accessResult.value = '已复制配置话术 · 粘贴到任意 AI 助手对话框'
}

const copyCursorConfig = () => copyClientConfig(selectedClientId.value)
const copyGuideUrl = () => copyText(guideUrl.value)
const copyGuidePrompt = () => copyAiAssistantPrompt()

const createKey = async () => {
  if (!panelAvailable.value) {
    accessResult.value = '开发模式可暂不配口令'
    return
  }
  const result = await safeJsonRequest('/api/aiopen/keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label: '面板' }),
  })
  if (result.ok && result.data?.success) {
    newKey.value = String(result.data.key || '')
    accessResult.value = '口令已生成，可选 AI 软件安装'
    await loadPanel()
  } else {
    accessResult.value = result.message || '生成失败'
  }
}

const quickSetup = async () => {
  if (readyStatus.value === 'ready') return
  setupRunning.value = true
  accessResult.value = ''
  try {
    if (panelAvailable.value) {
      const ctl = await safeJsonRequest('/api/aiopen/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: true }),
      })
      if (ctl.ok) remoteControlEnabled.value = true
      if (!hasConnectConfig.value) await createKey()
    } else {
      remoteControlEnabled.value = true
    }
    setCursorEnabled(true)
    accessResult.value = '已开启！选择上方 AI 软件完成 MCP 配置'
  } finally {
    setupRunning.value = false
  }
}

const toggleWhitelist = async (path, event) => {
  const enabled = Boolean(event?.target?.checked)
  routes.value = routes.value.map((item) => (item.path === path ? { ...item, enabled } : item))
  if (!panelAvailable.value) return
  await safeJsonRequest('/api/aiopen/whitelist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, enabled }),
  })
}

const toggleWechat = async (event) => {
  wechatOpen.value = Boolean(event?.target?.checked)
  if (!panelAvailable.value) return
  await safeJsonRequest('/api/ai/qclaw/wechat-gateway', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled: wechatOpen.value }),
  })
}

const toggleRemoteControl = async (event) => {
  remoteControlEnabled.value = Boolean(event?.target?.checked)
  if (!panelAvailable.value) return
  await safeJsonRequest('/api/aiopen/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled: remoteControlEnabled.value }),
  })
}

const toggleScreenSession = (event) => {
  setCursorEnabled(Boolean(event?.target?.checked))
}

const saveOpenclawBase = async () => {
  if (!panelAvailable.value) return
  const result = await safeJsonRequest('/api/aiopen/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ base_url: openclawBase.value }),
  })
  openclawResult.value = result.ok ? '已保存' : result.message
}

const sendToOpenclaw = async () => {
  openclawSending.value = true
  openclawResult.value = ''
  try {
    const result = await safeJsonRequest('/api/aiopen/openclaw/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: openclawMessage.value, source: 'aiopen' }),
    })
    const d = result?.data
    openclawResult.value = result.ok && d?.success ? '发送成功' : (result.message || '失败')
  } catch (err) {
    openclawResult.value = String(err?.message || err)
  } finally {
    openclawSending.value = false
  }
}

const openclawWsUrl = ref('ws://localhost:28789/ws')
const openclawWsAuthMode = ref('token')
const openclawGatewayToken = ref('')
const wsConnected = ref(false)
const wsConnecting = ref(false)
const wsStatusText = ref('')
let wsClient = null

const connectOpenclawWs = () => {
  if (wsConnected.value || wsConnecting.value) return
  wsConnecting.value = true
  try {
    wsClient = new WebSocket(String(openclawWsUrl.value || '').trim())
    wsClient.onopen = () => { wsConnecting.value = false; wsStatusText.value = 'WS 已连接' }
    wsClient.onmessage = (event) => {
      let msg = null
      try { msg = JSON.parse(String(event.data || '')) } catch { return }
      if (msg?.event === 'connect.challenge' && wsClient) {
        const secret = openclawGatewayToken.value.trim()
        if (!secret) return
        const auth = openclawWsAuthMode.value === 'password' ? { password: secret } : { token: secret }
        wsClient.send(JSON.stringify({
          type: 'req', id: `c_${Date.now()}`, method: 'connect',
          params: { minProtocol: 3, maxProtocol: 3, client: { id: 'openclaw-control-ui', version: '1.0.0', platform: 'windows', mode: 'ui' }, role: 'operator', scopes: ['operator.read', 'operator.write'], auth, locale: 'zh-CN' },
        }))
      }
      if (msg?.type === 'res' && msg?.payload?.type === 'hello-ok') wsConnected.value = true
    }
    wsClient.onclose = () => { wsConnecting.value = false; wsConnected.value = false; wsClient = null }
    wsClient.onerror = () => { wsStatusText.value = 'WS 失败' }
  } catch {
    wsConnecting.value = false
  }
}

onMounted(() => {
  try { oneLinerCopied.value = localStorage.getItem('aiopen_oneliner_copied') === '1' } catch { /* ignore */ }
  refreshInstalledClients()
  loadPanel()
})
onBeforeUnmount(() => { wsClient?.close(); wsClient = null })
</script>

<style scoped>
.aiopen-shell {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #f8fafc;
}
.aiopen-header {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
  flex-shrink: 0;
}
.aiopen-header-brand {
  text-align: center;
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
}
.aiopen-header-spacer {
  width: 72px;
}
.aiopen-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  justify-content: center;
  padding: 20px 20px 36px;
  background:
    radial-gradient(circle at 50% 0%, rgba(219, 234, 254, 0.45), transparent 55%),
    #f8fafc;
}
.aiopen-stage {
  width: 100%;
  max-width: 440px;
}
.aiopen-back {
  border: 1px solid #e2e8f0;
  background: #fff;
  color: #334155;
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
}
.aiopen-back:hover {
  color: #0f172a;
  border-color: #cbd5e1;
}

.aiopen-hero {
  width: 100%;
  padding: 0;
  border-radius: 20px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.35);
  box-shadow: 0 12px 40px rgba(30, 64, 175, 0.08);
  overflow: hidden;
}
.aiopen-hero--ready { border-color: rgba(34, 197, 94, 0.45); }
.aiopen-hero--partial { border-color: rgba(251, 191, 36, 0.5); }

.aiopen-hero-top {
  text-align: center;
  padding: 24px 24px 16px;
  background: linear-gradient(180deg, #f0f7ff 0%, #fff 100%);
}
.aiopen-hero--ready .aiopen-hero-top {
  background: linear-gradient(180deg, #ecfdf5 0%, #fff 100%);
}
.aiopen-hero-badge {
  display: inline-block;
  margin-bottom: 14px;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: #1d4ed8;
  background: rgba(219, 234, 254, 0.8);
  border: 1px solid #bfdbfe;
}
.aiopen-hero-icon-wrap {
  position: relative;
  width: 64px;
  height: 64px;
  margin: 0 auto 12px;
}
.aiopen-hero-icon {
  width: 64px;
  height: 64px;
  border-radius: 18px;
  background: linear-gradient(145deg, #3b82f6, #1d4ed8);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.35);
}
.aiopen-hero--ready .aiopen-hero-icon {
  background: linear-gradient(145deg, #22c55e, #16a34a);
  box-shadow: 0 8px 20px rgba(34, 197, 94, 0.35);
}
.aiopen-live-dot {
  position: absolute;
  right: 2px;
  bottom: 2px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #22c55e;
  border: 2px solid #fff;
  animation: aiopen-pulse 1.6s ease-in-out infinite;
}
@keyframes aiopen-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.85); }
}

.aiopen-hero-title {
  margin: 0 0 6px;
  font-size: 26px;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: 0.06em;
}
.aiopen-hero-tagline {
  margin: 0;
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
}

.aiopen-features {
  list-style: none;
  margin: 0;
  padding: 14px 20px;
  display: grid;
  gap: 10px;
  border-top: 1px solid #f1f5f9;
  border-bottom: 1px solid #f1f5f9;
  background: #fafbfc;
}
.aiopen-features li {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  font-size: 12px;
  line-height: 1.45;
}
.aiopen-feature-icon {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: #2563eb;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.aiopen-features strong {
  display: block;
  color: #0f172a;
  font-size: 13px;
  margin-bottom: 1px;
}
.aiopen-features span {
  color: #64748b;
}

.aiopen-flow {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 12px 16px 0;
  flex-wrap: wrap;
}
.aiopen-flow-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #94a3b8;
  padding: 4px 8px;
  border-radius: 999px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}
.aiopen-flow-item.done {
  color: #15803d;
  background: #f0fdf4;
  border-color: #bbf7d0;
}
.aiopen-flow-item em {
  font-style: normal;
  font-weight: 700;
  font-size: 10px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #e2e8f0;
  color: #475569;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.aiopen-flow-item.done em {
  background: #22c55e;
  color: #fff;
}

.aiopen-hero-status {
  margin: 10px 20px 0;
  font-size: 12px;
  color: #64748b;
  text-align: center;
  line-height: 1.45;
}
.aiopen-hero-warn {
  margin: 6px 20px 0;
  font-size: 11px;
  color: #b45309;
  text-align: center;
}

.aiopen-primary-btn {
  display: block;
  width: calc(100% - 40px);
  margin: 14px 20px 10px;
  padding: 13px;
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  border: none;
  border-radius: 12px;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(37, 99, 235, 0.3);
}
.aiopen-primary-btn:hover:not(:disabled) { filter: brightness(1.05); }
.aiopen-primary-btn:disabled { opacity: 0.55; cursor: default; box-shadow: none; }

.aiopen-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  padding: 0 20px 20px;
}

.aiopen-oneline {
  margin: 0 20px 14px;
  padding: 12px;
  border-radius: 12px;
  background: linear-gradient(135deg, #f0f9ff 0%, #eff6ff 100%);
  border: 1px solid #bfdbfe;
}
.aiopen-oneline-label {
  margin: 0 0 6px;
  font-size: 11px;
  font-weight: 600;
  color: #1d4ed8;
  letter-spacing: 0.02em;
}
.aiopen-oneline-preview {
  margin: 0 0 10px;
  font-size: 12px;
  line-height: 1.5;
  color: #475569;
  word-break: break-all;
}
.aiopen-oneline-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.aiopen-oneline-btn {
  padding: 9px 10px;
  border-radius: 10px;
  border: none;
  background: #2563eb;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.aiopen-oneline-btn:hover { filter: brightness(1.05); }
.aiopen-oneline-btn--ghost {
  background: #fff;
  color: #2563eb;
  border: 1px solid #93c5fd;
}

.aiopen-client-section {
  padding: 0 20px 16px;
}
.aiopen-client-title {
  margin: 0 0 10px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  text-align: center;
}
.aiopen-client-sub {
  font-weight: 400;
  color: #94a3b8;
  font-size: 11px;
}
.aiopen-client-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.aiopen-client-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 10px 6px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}
.aiopen-client-btn:hover {
  border-color: #93c5fd;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.08);
}
.aiopen-client-btn.done {
  border-color: #86efac;
  background: #f0fdf4;
}
.aiopen-client-icon {
  font-size: 16px;
  line-height: 1;
  color: #2563eb;
}
.aiopen-client-btn.done .aiopen-client-icon { color: #16a34a; }
.aiopen-client-name {
  font-size: 12px;
  font-weight: 700;
  color: #1e293b;
}
.aiopen-client-action {
  font-size: 9px;
  color: #94a3b8;
}
.aiopen-guide-link {
  display: block;
  width: 100%;
  margin-top: 10px;
  border: none;
  background: none;
  color: #64748b;
  font-size: 11px;
  cursor: pointer;
  text-align: center;
  padding: 4px 0;
}
.aiopen-guide-link:hover { color: #2563eb; }
.aiopen-guide-link--primary {
  display: block;
  width: 100%;
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  text-align: center;
}
.aiopen-guide-link--primary:hover {
  background: #dbeafe;
  color: #1e40af;
}
.aiopen-guide-hint {
  margin: 6px 0 0;
  font-size: 10px;
  color: #94a3b8;
  text-align: center;
  line-height: 1.4;
}

.aiopen-client-picker {
  margin: 10px 0;
}
.aiopen-client-picker-label {
  display: block;
  font-size: 11px;
  color: #64748b;
  margin-bottom: 4px;
}
.aiopen-client-select {
  width: 100%;
  margin-bottom: 4px;
}
.aiopen-client-picker-hint {
  margin: 0;
  font-size: 10px;
  color: #94a3b8;
  line-height: 1.4;
}

.aiopen-secondary-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 10px 8px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.aiopen-secondary-btn:hover {
  border-color: #93c5fd;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.08);
}
.aiopen-btn-label {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}
.aiopen-btn-hint {
  font-size: 10px;
  color: #94a3b8;
}

.aiopen-mcp-health {
  margin: 4px 20px 0;
  font-size: 11px;
  color: #94a3b8;
  text-align: center;
}
.aiopen-mcp-health.ok { color: #15803d; }

.aiopen-secondary-btn--primary {
  border-color: #93c5fd;
  background: #eff6ff;
}
.aiopen-secondary-btn--primary .aiopen-btn-label { color: #1d4ed8; }

.aiopen-tools-preview {
  margin: 0 20px 16px;
  font-size: 11px;
  color: #64748b;
}
.aiopen-tools-preview > summary {
  cursor: pointer;
  text-align: center;
  list-style: none;
  padding: 6px 0;
}
.aiopen-tools-preview > summary::-webkit-details-marker { display: none; }
.aiopen-tools-preview ul {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: grid;
  gap: 6px;
  max-height: 140px;
  overflow: auto;
}
.aiopen-tools-preview li {
  padding: 6px 8px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}
.aiopen-tools-preview strong {
  display: block;
  font-size: 12px;
  color: #0f172a;
}
.aiopen-tools-preview span { color: #64748b; }

.aiopen-toast {
  margin: 0 20px 16px;
  padding: 8px 12px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  font-size: 12px;
  color: #1d4ed8;
  line-height: 1.4;
  text-align: center;
}

.aiopen-more {
  width: 100%;
  margin-top: 16px;
  font-size: 13px;
  color: #94a3b8;
}
.aiopen-more > summary {
  cursor: pointer;
  text-align: center;
  list-style: none;
  user-select: none;
}
.aiopen-more > summary::-webkit-details-marker { display: none; }
.aiopen-more-body {
  margin-top: 12px;
  padding: 14px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}
.aiopen-link-btn {
  border: none;
  background: none;
  color: #2563eb;
  font-size: 12px;
  cursor: pointer;
  padding: 0;
  margin-bottom: 10px;
}
.aiopen-offline-hint {
  margin: 0 0 10px;
  font-size: 11px;
  color: #b45309;
  line-height: 1.4;
}
.aiopen-switch-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
  color: #475569;
  cursor: pointer;
}
.aiopen-more-actions { display: flex; gap: 8px; margin: 10px 0; flex-wrap: wrap; }
.aiopen-nested { margin-top: 10px; font-size: 12px; }
.aiopen-nested summary { cursor: pointer; color: #64748b; }
.aiopen-advanced-body { margin-top: 10px; }
.aiopen-pre, .aiopen-endpoint-code, .aiopen-tool-item, .aiopen-route-item, .aiopen-row, .aiopen-input, .aiopen-select, .aiopen-result, .aiopen-tools, .aiopen-route-list, .aiopen-endpoint-row {
  font-size: 11px;
}
.aiopen-pre {
  padding: 8px;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 6px;
  overflow: auto;
  max-height: 100px;
  white-space: pre-wrap;
  word-break: break-all;
}
.aiopen-endpoint-row { display: flex; gap: 6px; margin: 6px 0; align-items: center; }
.aiopen-endpoint-code { flex: 1; overflow: hidden; text-overflow: ellipsis; background: #f1f5f9; padding: 4px 6px; border-radius: 4px; }
.aiopen-tools, .aiopen-route-list { display: grid; gap: 4px; max-height: 120px; overflow: auto; margin: 6px 0; }
.aiopen-tool-item, .aiopen-route-item { display: flex; gap: 6px; padding: 4px; background: #f8fafc; border-radius: 4px; }
.aiopen-row { display: grid; grid-template-columns: 1fr auto; gap: 6px; margin: 6px 0; }
.aiopen-row-auth { grid-template-columns: auto 1fr; }
.aiopen-input, .aiopen-select { border: 1px solid #d1d5db; border-radius: 6px; padding: 5px 8px; min-width: 0; }
.aiopen-result { color: #64748b; min-height: 16px; }
</style>
