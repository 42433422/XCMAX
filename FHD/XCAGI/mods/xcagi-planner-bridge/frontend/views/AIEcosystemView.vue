<template>
  <div class="chat-view page-view active" id="view-ai-ecosystem">
    <div v-if="!inAnalyzer" class="ecosystem-home">
      <div class="ecosystem-home-title">AI生态应用</div>
      <div class="launcher-grid">
        <button class="app-launcher" type="button" @click="enterAnalyzer('kitten')">
          <span class="app-launcher-icon app-launcher-icon--kitten" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M7.2 10.2 5.4 4.8 9.2 8.4Z" fill="#fff" />
              <path d="M16.8 10.2 18.6 4.8 14.8 8.4Z" fill="#fff" />
              <circle cx="12" cy="12.8" r="5.2" fill="#fff" />
              <circle cx="10.3" cy="11.8" r="0.95" fill="#ea580c" />
              <circle cx="13.7" cy="11.8" r="0.95" fill="#ea580c" />
              <ellipse cx="12" cy="14.2" rx="1.1" ry="0.75" fill="#fb923c" />
              <rect x="4.2" y="17.2" width="2.2" height="3.6" rx="0.55" fill="#fff" opacity="0.82" />
              <rect x="8.1" y="15.4" width="2.2" height="5.4" rx="0.55" fill="#fff" opacity="0.9" />
              <rect x="13.7" y="16.3" width="2.2" height="4.5" rx="0.55" fill="#fff" opacity="0.9" />
              <rect x="17.6" y="14.5" width="2.2" height="6.3" rx="0.55" fill="#fff" />
            </svg>
          </span>
          <span class="app-launcher-name">小猫分析</span>
          <span class="app-launcher-desc">上传表格、对话分析、生成丰富图表，并按需导出报告</span>
        </button>
        <button class="app-launcher" type="button" @click="enterAnalyzer('qclaw')">
          <span class="app-launcher-icon app-launcher-icon--qclaw" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <circle cx="5.5" cy="5.5" r="2.2" fill="#fff" opacity="0.92" />
              <circle cx="18.5" cy="5.5" r="2.2" fill="#fff" opacity="0.92" />
              <circle cx="5.5" cy="18.5" r="2.2" fill="#fff" opacity="0.92" />
              <circle cx="18.5" cy="18.5" r="2.2" fill="#fff" opacity="0.92" />
              <circle cx="12" cy="12" r="3.1" fill="#fff" />
              <path d="M7.4 7.1 10 10M14 10 16.6 7.1M7.4 16.9 10 14M14 14 16.6 16.9" stroke="#fff" stroke-width="1.45" stroke-linecap="round" opacity="0.88" />
            </svg>
          </span>
          <span class="app-launcher-name">Qclaw龙虾生态</span>
          <span class="app-launcher-desc">龙虾业务数据洞察与经营分析</span>
        </button>
        <button class="app-launcher" type="button" @click="goShellPage('brain')">
          <span class="app-launcher-icon app-launcher-icon--brain" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M12 4.2c-3.2 0-5.2 2.3-5.2 4.8 0 1.1.35 2.1.92 2.95-.58.78-.92 1.72-.92 2.75 0 2.05 1.75 3.7 4.3 3.7h2.8c2.55 0 4.3-1.65 4.3-3.7 0-1.03-.34-1.97-.92-2.75.57-.85.92-1.85.92-2.95 0-2.5-2-4.8-5.2-4.8Z" fill="#fff" opacity="0.96" />
              <path d="M9.6 10.4c0 .75.65 1.35 1.4 1.35M13 10.4c0 .75.65 1.35 1.4 1.35M10.1 14.1c.75.75 2.05.75 2.8 0" stroke="#7c3aed" stroke-width="1.15" stroke-linecap="round" />
              <circle cx="10.2" cy="9.1" r="0.85" fill="#7c3aed" />
              <circle cx="13.8" cy="9.1" r="0.85" fill="#7c3aed" />
            </svg>
          </span>
          <span class="app-launcher-name">AI智脑集成</span>
          <span class="app-launcher-desc">Agent 控制台，同源 Planner 与 unified_chat 联调</span>
        </button>
        <button class="app-launcher" type="button" @click="goShellPage('mod-store')">
          <span class="app-launcher-icon app-launcher-icon--store" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <rect x="4.2" y="4.2" width="6.8" height="6.8" rx="2" fill="#fff" opacity="0.96" />
              <rect x="13" y="4.2" width="6.8" height="6.8" rx="2" fill="#fff" opacity="0.88" />
              <rect x="4.2" y="13" width="6.8" height="6.8" rx="2" fill="#fff" opacity="0.88" />
              <rect x="13" y="13" width="6.8" height="6.8" rx="2" fill="#fff" opacity="0.78" />
              <path d="M16.4 15.8h2.2M17.5 14.7v2.2" stroke="#1d4ed8" stroke-width="1.6" stroke-linecap="round" />
            </svg>
          </span>
          <span class="app-launcher-name">员工商店</span>
          <span class="app-launcher-desc">MOD 扩展浏览、安装与本机 .xcmod 目录</span>
        </button>
      </div>
    </div>

    <KittenAnalyzerView v-else-if="activeApp === 'kitten'" @back="exitAnalyzer" />

    <template v-else>
      <div class="qclaw-shell">
        <div class="qclaw-header">
          <button class="qclaw-back" type="button" @click="exitAnalyzer">返回应用列表</button>
          <div class="qclaw-title">Qclaw龙虾生态 · 路由调度面板</div>
          <button class="qclaw-refresh" type="button" @click="loadQclawPanel">刷新</button>
        </div>

        <div class="qclaw-grid">
          <section class="qclaw-card">
            <h3>微信开放权限开关</h3>
            <label class="qclaw-switch-row">
              <input type="checkbox" :checked="qclawWechatOpen" @change="toggleQclawWechat($event)">
              <span>{{ qclawWechatOpen ? '已开放' : '已关闭' }}</span>
            </label>
          </section>

          <section class="qclaw-card">
            <h3>路由白名单可视化</h3>
            <div class="qclaw-route-list">
              <label v-for="route in qclawRoutes" :key="route.path" class="qclaw-route-item">
                <input type="checkbox" :checked="route.enabled" @change="toggleWhitelistRoute(route.path, $event)">
                <code>{{ route.path }}</code>
              </label>
            </div>
          </section>

          <section class="qclaw-card">
            <h3>一键测试各路由</h3>
            <div class="qclaw-actions">
              <button class="btn btn-primary btn-sm" type="button" :disabled="qclawTesting" @click="testAllRoutes">
                {{ qclawTesting ? '测试中...' : '测试全部已启用路由' }}
              </button>
            </div>
            <div class="qclaw-test-list">
              <div v-for="item in qclawTestResults" :key="item.path + item.method" class="qclaw-test-item">
                <span class="route-text">{{ item.path }}</span>
                <span :class="item.result === 'ok' ? 'ok' : 'fail'">{{ item.result }} ({{ item.status_code }})</span>
              </div>
            </div>
          </section>

          <section class="qclaw-card">
            <h3>OpenClaw 联调</h3>
            <div class="qclaw-openclaw-row">
              <input v-model="openclawBase" class="qclaw-input" placeholder="http://localhost:28789">
              <button class="btn btn-secondary btn-sm" type="button" @click="saveOpenclawBase">保存</button>
            </div>
            <div class="qclaw-openclaw-row">
              <input v-model="openclawMessage" class="qclaw-input" placeholder="输入要发给 OpenClaw 的消息">
              <button class="btn btn-primary btn-sm" type="button" :disabled="openclawSending" @click="sendToOpenclaw">
                {{ openclawSending ? '发送中...' : '发送' }}
              </button>
            </div>
            <div class="qclaw-openclaw-result">{{ openclawResult || '等待发送...' }}</div>
          </section>

          <section class="qclaw-card">
            <h3>OpenClaw WebSocket 流式联调</h3>
            <div class="qclaw-ws-device-callout">
              握手报 <code>CONTROL_UI_DEVICE_IDENTITY_REQUIRED</code> /「control ui requires device identity」时，提示文案<strong>容易误导</strong>：网关实际检查的是
              <code>gateway.controlUi.allowInsecureAuth === true</code> <strong>且</strong> TCP 被判定为<strong>本机直连</strong>（<code>isLocalClient</code>），与浏览器是否 Secure Context 不是一回事。
              <br><br>
              <strong>必查 ①</strong> 在<strong>正在跑网关的那台机子</strong>上执行
              <code>openclaw config get gateway.controlUi.allowInsecureAuth</code>，须为 <code>true</code>；否则
              <code>openclaw config set gateway.controlUi.allowInsecureAuth true</code> 后 <code>openclaw gateway restart</code>（生效的是用户目录里的 <code>openclaw.json</code>，不是 XCAGI 仓库）。
              <br>
              <strong>必查 ②</strong> WebSocket 用 <code>ws://localhost:端口/ws</code>，勿用局域网 IP。
              <br>
              <strong>常见坑 ③</strong> 网关跑在 <strong>Docker / WSL 端口映射</strong> 时，容器里看到的源地址常<strong>不是</strong> 127.0.0.1，<code>isLocalClient</code> 会为 false——即使用 <code>localhost</code> 也会同样报错。可改用容器 host 网络、或按官方文档开启
              <code>gateway.allowRealIpFallback</code> / 可信代理；仍不行时仅联调可临时
              <code>openclaw config set gateway.controlUi.dangerouslyDisableDeviceAuth true</code>（安全性下降，用完请关）。
            </div>
            <p class="qclaw-ws-auth-hint">
              <strong>token</strong>：在下方填写与网关一致的共享密钥，对应环境变量
              <code>OPENCLAW_GATEWAY_TOKEN</code>（协议里为 <code>connect.params.auth.token</code>，错误码里常写作 AUTH_TOKEN）。
              <strong>password</strong>：将下方认证改为「密码」，请求体会发
              <code>auth.password</code>，对应 <code>OPENCLAW_GATEWAY_PASSWORD</code>。
              不确定网关当前模式时在终端执行：
              <code>openclaw config get gateway.auth.mode</code>
            </p>
            <details class="qclaw-ws-details">
              <summary>控制 UI / 设备身份：方案 A（推荐）与方案 B</summary>
              <p class="qclaw-ws-auth-hint">
                若控制 UI 或 WebSocket 因设备校验失败，可用 <strong>方案 A</strong>（比 <code>dangerouslyDisableDeviceAuth</code> 更安全）：
              </p>
              <pre class="qclaw-pre">openclaw config get gateway.controlUi.allowInsecureAuth
openclaw config set gateway.controlUi.dangerouslyDisableDeviceAuth false
openclaw config set gateway.controlUi.allowInsecureAuth true
openclaw gateway restart</pre>
              <p class="qclaw-ws-auth-hint">
                <strong>方案 B（最安全）</strong>：安装 PyNaCl 并在客户端按网关要求完成设备签名：<code>pip install pynacl</code>（再按文档实现 Ed25519 签名）。
              </p>
              <p class="qclaw-ws-auth-hint">
                QClaw 自带的 <code>openclaw.json</code> 模板已默认 <code>allowInsecureAuth: true</code>、<code>dangerouslyDisableDeviceAuth: false</code>；若你使用用户目录下的配置，请用上面命令同步。
              </p>
              <p class="qclaw-ws-auth-hint">
                联调使用 <code>openclaw-control-ui</code> 身份以保留 <code>operator.write</code>；若握手报 <code>origin not allowed</code>，请在
                <code>gateway.controlUi.allowedOrigins</code> 中加入你访问 XCAGI 的页面来源（例如 <code>http://localhost:5000</code>）。
              </p>
            </details>
            <div class="qclaw-openclaw-row qclaw-openclaw-row-auth">
              <label class="qclaw-ws-auth-label">认证</label>
              <select v-model="openclawWsAuthMode" class="qclaw-select">
                <option value="token">token（OPENCLAW_GATEWAY_TOKEN）</option>
                <option value="password">password（OPENCLAW_GATEWAY_PASSWORD）</option>
              </select>
              <input
                v-model="openclawGatewayToken"
                class="qclaw-input qclaw-input-grow"
                :type="openclawWsAuthMode === 'password' ? 'password' : 'text'"
                :placeholder="openclawWsAuthMode === 'password' ? '网关密码（auth.password）' : '网关 Token（auth.token）'"
              >
              <span class="qclaw-hint">Challenge-Response</span>
            </div>
            <div class="qclaw-openclaw-row">
              <input v-model="openclawWsUrl" class="qclaw-input" placeholder="ws://localhost:28789/ws">
              <div class="qclaw-inline-actions">
                <button
                  class="btn btn-secondary btn-sm"
                  type="button"
                  @click.stop="normalizeOpenclawWsToLoopback"
                >
                  改为 localhost
                </button>
                <button class="btn btn-secondary btn-sm" type="button" :disabled="wsConnected || wsConnecting" @click="connectOpenclawWs">
                  {{ wsConnecting ? '连接中...' : '连接' }}
                </button>
                <button class="btn btn-secondary btn-sm" type="button" :disabled="!wsConnected" @click="disconnectOpenclawWs">
                  断开
                </button>
              </div>
            </div>
            <div class="qclaw-openclaw-row">
              <input v-model="openclawWsSessionKey" class="qclaw-input" placeholder="sessionKey（如 main，须为网关已有会话）">
              <span class="qclaw-hint">网关 schema 要求 sessionKey + idempotencyKey（面板已自动生成后者）</span>
            </div>
            <p class="qclaw-ws-auth-hint">
              命令行可参考仓库内可运行脚本：<code>scripts/openclaw_ws_chat_example.py</code>（与当前网关协议对齐，含正确 <code>connect</code> 与 <code>event: chat</code>）。
            </p>
            <div class="qclaw-openclaw-row">
              <input v-model="openclawWsMessage" class="qclaw-input" placeholder="消息正文">
              <button class="btn btn-primary btn-sm" type="button" :disabled="!wsConnected" @click="sendOpenclawWsMessage">
                发送
              </button>
            </div>
            <div class="qclaw-openclaw-result">{{ wsStatusText }}</div>
            <div v-if="wsReplyPreview" class="qclaw-openclaw-result qclaw-ws-reply">助手：{{ wsReplyPreview }}</div>
            <div class="qclaw-ws-log">
              <div v-for="(line, idx) in wsLogs" :key="idx">{{ line }}</div>
            </div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onBeforeUnmount, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import { safeJsonRequest } from '@/utils/safeJsonRequest'
import { resolvePlannerPageRedirectForRouteName } from '@/utils/plannerPagePaths'

const router = useRouter()

const KittenAnalyzerView = defineAsyncComponent(() => import('@/components/kitten/KittenAnalyzerView.vue'))

const inAnalyzer = ref(false)
const activeApp = ref('kitten')
const qclawWechatOpen = ref(false)
const qclawRoutes = ref([])
const qclawTestResults = ref([])
const qclawTesting = ref(false)
const openclawBase = ref('http://localhost:28789')
const openclawMessage = ref('你好')
const openclawSending = ref(false)
const openclawResult = ref('')
const openclawWsUrl = ref('ws://localhost:28789/ws')
/** 须指向网关中已存在的会话，默认 main */
const openclawWsSessionKey = ref('main')
const openclawWsMessage = ref('你好')
/** token → connect.params.auth.token；password → auth.password（与 gateway.auth.mode 一致） */
const openclawWsAuthMode = ref('token')
const openclawGatewayToken = ref('')
const wsConnected = ref(false)
const wsConnecting = ref(false)
const wsStatusText = ref('未连接')
/** 网关 event:chat 推送的助手文本（非 chat.progress） */
const wsReplyPreview = ref('')
const wsLogs = ref([])
let wsClient = null
let wsLastChatReqId = ''
const MAX_WS_LOGS = 300

const pushBounded = (arrRef, item, maxSize) => {
  arrRef.value.push(item)
  const overflow = arrRef.value.length - maxSize
  if (overflow > 0) {
    arrRef.value.splice(0, overflow)
  }
}

const pushWsLog = (text) => pushBounded(wsLogs, text, MAX_WS_LOGS)

const extractAssistantTextFromChatPayload = (p) => {
  const msg = p?.message
  if (!msg) return ''
  const parts = msg.content
  if (!Array.isArray(parts)) return ''
  return parts
    .map((c) => (c && c.type === 'text' && typeof c.text === 'string' ? c.text : ''))
    .join('')
}

const goShellPage = (name) => {
  const modPath = resolvePlannerPageRedirectForRouteName(name)
  if (modPath) {
    router.push(modPath)
    return
  }
  router.push({ name })
}

const enterAnalyzer = (appKey = 'kitten') => {
  activeApp.value = appKey
  inAnalyzer.value = true
  if (appKey === 'qclaw') {
    loadQclawPanel()
  }
}

const exitAnalyzer = () => {
  inAnalyzer.value = false
}

const loadQclawPanel = async () => {
  try {
    const result = await safeJsonRequest('/api/ai/qclaw/panel')
    if (result.ok && result.data?.success) {
      qclawWechatOpen.value = Boolean(result.data.wechat_open)
      qclawRoutes.value = Array.isArray(result.data.routes) ? result.data.routes : []
      openclawBase.value = String(result.data.openclaw_base || 'http://localhost:28789')
      openclawResult.value = ''
    } else {
      qclawRoutes.value = []
      openclawResult.value = result.message || '加载面板失败'
    }
  } catch (_err) {
    qclawRoutes.value = []
    openclawResult.value = '加载面板失败：网络异常'
  }
}

const toggleQclawWechat = async (event) => {
  const enabled = Boolean(event?.target?.checked)
  qclawWechatOpen.value = enabled
  const result = await safeJsonRequest('/api/ai/qclaw/wechat-gateway', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled })
  })
  if (!result.ok) {
    openclawResult.value = result.message
  }
}

const toggleWhitelistRoute = async (path, event) => {
  const enabled = Boolean(event?.target?.checked)
  qclawRoutes.value = qclawRoutes.value.map((item) => item.path === path ? { ...item, enabled } : item)
  const result = await safeJsonRequest('/api/ai/qclaw/whitelist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, enabled })
  })
  if (!result.ok) {
    openclawResult.value = result.message
  }
}

const testAllRoutes = async () => {
  qclawTesting.value = true
  qclawTestResults.value = []
  const enabledRoutes = qclawRoutes.value.filter((item) => item.enabled)
  for (const route of enabledRoutes) {
    try {
      const result = await safeJsonRequest('/api/ai/qclaw/test-route', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: route.path, method: route.path.includes('/chat') ? 'POST' : 'GET' })
      })
      qclawTestResults.value.push({
        path: route.path,
        method: route.path.includes('/chat') ? 'POST' : 'GET',
        result: result.ok ? (result.data?.result || 'ok') : 'error',
        status_code: result.data?.status_code || result.status
      })
    } catch (_err) {
      qclawTestResults.value.push({
        path: route.path,
        method: 'GET',
        result: 'error',
        status_code: 500
      })
    }
  }
  qclawTesting.value = false
}

const saveOpenclawBase = async () => {
  const result = await safeJsonRequest('/api/ai/qclaw/openclaw/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ base_url: openclawBase.value })
  })
  openclawResult.value = result.ok ? 'OpenClaw 地址已保存' : result.message
}

const sendToOpenclaw = async () => {
  openclawSending.value = true
  openclawResult.value = ''
  try {
    const result = await safeJsonRequest('/api/ai/qclaw/openclaw/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: openclawMessage.value, source: 'qclaw' })
    })
    const resultData = result && result.data ? result.data : null
    const payload = resultData && resultData.data ? resultData.data : null
    if (result.ok && resultData && resultData.success) {
      const show = (payload && payload.message) || (payload && payload.response) || JSON.stringify(payload || {})
      openclawResult.value = `成功：${show}`
    } else {
      openclawResult.value = `失败：${result.message || '未知错误'}`
    }
  } catch (err) {
    const errMessage = err && err.message ? err.message : err
    openclawResult.value = `失败：${errMessage}`
  } finally {
    openclawSending.value = false
  }
}

const normalizeOpenclawWsToLoopback = () => {
  const s = String(openclawWsUrl.value || '').trim()
  if (!s) {
    openclawWsUrl.value = 'ws://localhost:28789/ws'
    wsStatusText.value = '已填入默认 ws://localhost:28789/ws'
    return
  }
  const before = s
  let next = s
  try {
    const u = new URL(s)
    u.hostname = 'localhost'
    next = u.toString()
  } catch (_err) {
    const mm = s.match(/^((?:ws|wss)):\/\/([^/]+)(\/.*)?$/i)
    if (mm) {
      const proto = mm[1].toLowerCase()
      const hp = mm[2]
      const port = hp.includes(':') ? hp.slice(hp.indexOf(':')) : ''
      const path = mm[3] || ''
      next = `${proto}://localhost${port}${path}`
    }
  }
  openclawWsUrl.value = next
  if (before === next) {
    wsStatusText.value = '已是本机回环地址，无需修改'
  } else {
    wsStatusText.value = `已改为: ${next}`
  }
}

const connectOpenclawWs = () => {
  if (wsConnected.value || wsConnecting.value) return
  wsConnecting.value = true
  wsStatusText.value = '连接中...'
  wsLogs.value = []
  wsReplyPreview.value = ''
  try {
    const wsUrl = String(openclawWsUrl.value || '').trim()
    try {
      const u = new URL(wsUrl)
      const h = String(u.hostname || '').toLowerCase()
      const loopbackHost = h === 'localhost' || h === '127.0.0.1' || h === '[::1]'
      if (!loopbackHost) {
        pushWsLog('[warn] WS 主机非本机回环；建议用 ws://localhost:端口/ws，避免握手失败。')
      }
    } catch (_ignore) {
      // ignore
    }

    wsClient = new WebSocket(wsUrl)
    wsClient.onopen = () => {
      wsConnecting.value = false
      wsStatusText.value = '已建立连接，等待 challenge...'
      pushWsLog('[open] websocket connected, waiting challenge')
    }

    wsClient.onmessage = (event) => {
      const raw = String(event.data || '')
      let msg = null
      try {
        msg = JSON.parse(raw)
      } catch (_err) {
        pushWsLog(`[parse] ${raw.slice(0, 240)}`)
        return
      }

      const msgType = msg && msg.type
      const msgEvent = msg && msg.event
      const msgPayload = (msg && msg.payload) || {}
      const msgError = (msg && msg.error) || {}

      if (msgEvent === 'connect.challenge') {
        sendWsConnect(msgPayload.nonce, msgPayload.ts)
        return
      }

      if (msgType === 'res' && msgPayload.type === 'hello-ok') {
        wsConnected.value = true
        wsStatusText.value = '认证通过，已连接'
        pushWsLog('[auth] hello-ok')
        return
      }

      if (msgType === 'res' && msg && msg.ok === false && msgError) {
        const isChatAck = Boolean(wsLastChatReqId && msg.id === wsLastChatReqId)
        if (!isChatAck) {
          const dcode = msgError.details && msgError.details.code
          if (dcode === 'CONTROL_UI_DEVICE_IDENTITY_REQUIRED') {
            pushWsLog('[hint] 请检查 allowInsecureAuth=true 且网关重启生效。')
            pushWsLog('[hint] 请使用 ws://localhost:端口/ws，避免网关判定非本机。')
            wsStatusText.value = '握手失败：Control UI 设备身份校验未通过'
          } else {
            wsStatusText.value = `握手失败: ${msgError.message || dcode || 'unknown'}`
          }
          pushWsLog(`[res error] ${msgError.message || JSON.stringify(msgError)}`)
          return
        }
      }

      if (msgType === 'res' && wsLastChatReqId && msg && msg.id === wsLastChatReqId) {
        if (msg.ok) {
          pushWsLog(`[chat.send] 已接受 ${JSON.stringify(msgPayload || {})}`)
          wsStatusText.value = '已发送，等待模型回复…'
        } else {
          const errMsg = msgError.message || JSON.stringify(msgError || {})
          pushWsLog(`[chat.send] 失败 ${errMsg}`)
          wsStatusText.value = `发送失败: ${errMsg}`
        }
        return
      }

      if (msgType === 'event' && msgEvent === 'chat') {
        if (msgPayload.state === 'error') {
          const em = msgPayload.errorMessage || 'unknown'
          pushWsLog(`[chat error] ${em}`)
          wsReplyPreview.value = ''
          wsStatusText.value = `对话错误: ${em}`
          return
        }
        const text = extractAssistantTextFromChatPayload(msgPayload)
        if (text) {
          wsReplyPreview.value = text
          wsStatusText.value = msgPayload.state === 'final' ? '回复完成' : '模型输出中…'
          if (msgPayload.state === 'final') {
            pushWsLog(`[assistant final] ${text}`)
          }
        }
        return
      }

      if (msgEvent === 'chat.progress') {
        const text = (msgPayload && msgPayload.text) || ''
        if (text) {
          wsReplyPreview.value = (wsReplyPreview.value || '') + text
          pushWsLog(`[progress] ${text}`)
        }
        return
      }

      pushWsLog(raw.length > 600 ? `[message] ${raw.slice(0, 600)}…` : `[message] ${raw}`)
    }

    wsClient.onerror = () => {
      wsStatusText.value = '连接异常'
      pushWsLog('[error] websocket error')
    }
    wsClient.onclose = () => {
      wsConnecting.value = false
      wsConnected.value = false
      wsStatusText.value = '已断开'
      pushWsLog('[close] websocket closed')
      wsClient = null
    }
  } catch (err) {
    wsConnecting.value = false
    wsConnected.value = false
    wsStatusText.value = `连接失败: ${err && err.message ? err.message : err}`
  }
}

const disconnectOpenclawWs = () => {
  if (wsClient) {
    wsClient.close()
  }
}

const sendOpenclawWsMessage = () => {
  if (!wsClient || !wsConnected.value) return
  const message = String(openclawWsMessage.value || '').trim()
  if (!message) return
  const sessionKey = String(openclawWsSessionKey.value || '').trim() || 'main'
  const reqId = makeReqId()
  wsLastChatReqId = reqId
  wsReplyPreview.value = ''
  const idempotencyKey = makeReqId()
  const payload = {
    type: 'req',
    id: reqId,
    method: 'chat.send',
    params: {
      sessionKey,
      message,
      idempotencyKey
    }
  }
  wsClient.send(JSON.stringify(payload))
  pushWsLog(`[send] chat.send id=${reqId} sessionKey=${sessionKey}`)
}

const sendWsConnect = (nonce, ts) => {
  if (!wsClient) return
  const secret = openclawGatewayToken.value.trim()
  if (!secret) {
    wsStatusText.value = openclawWsAuthMode.value === 'password' ? '缺少 Gateway 密码' : '缺少 Gateway Token'
    pushWsLog(
      openclawWsAuthMode.value === 'password'
        ? '[auth] missing password (set OPENCLAW_GATEWAY_PASSWORD or gateway.auth.password)'
        : '[auth] missing token (set OPENCLAW_GATEWAY_TOKEN or gateway.auth.token)'
    )
    return
  }
  const auth =
    openclawWsAuthMode.value === 'password'
      ? { password: secret }
      : { token: secret }
  const reqId = makeReqId()
  // OpenClaw：无 device 时仅 Control UI 客户端会保留 scopes；cli + token 会被 clearUnboundScopes 清空导致 chat.send 报 missing scope: operator.write。
  // 使用 openclaw-control-ui + ui，与官方控制面一致，并在 allowInsecureAuth + 本机访问下保留 operator 作用域。
  const payload = {
    type: 'req',
    id: reqId,
    method: 'connect',
    params: {
      minProtocol: 3,
      maxProtocol: 3,
      client: {
        id: 'openclaw-control-ui',
        version: '1.0.0',
        platform: 'windows',
        mode: 'ui'
      },
      role: 'operator',
      scopes: ['operator.read', 'operator.write', 'operator.approvals', 'operator.pairing'],
      caps: [],
      commands: [],
      permissions: {},
      auth,
      locale: 'zh-CN',
      userAgent: 'xcagi-qclaw/1.0'
    }
  }
  wsClient.send(JSON.stringify(payload))
  pushWsLog(`[auth] send connect id=${reqId} nonce=${String(nonce || '')} ts=${String(ts || '')}`)
}

const makeReqId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `req_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

onBeforeUnmount(() => {
  if (wsClient) {
    wsClient.close()
    wsClient = null
  }
})
</script>

<style scoped>
.chat-view { height: 100%; display: flex; flex-direction: column; }
.ecosystem-home {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
  padding: 24px;
  background:
    radial-gradient(circle at 12% 8%, rgba(251, 191, 36, 0.12), transparent 28%),
    radial-gradient(circle at 88% 18%, rgba(59, 130, 246, 0.1), transparent 30%),
    linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
}
.ecosystem-home-title {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: #0f172a;
}
.launcher-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 248px));
  gap: 20px;
}
.app-launcher {
  width: 248px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: rgba(255, 255, 255, 0.92);
  border-radius: 18px;
  padding: 22px 18px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.06);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.app-launcher:hover {
  transform: translateY(-3px);
  border-color: rgba(191, 219, 254, 0.95);
  box-shadow: 0 16px 34px rgba(30, 64, 175, 0.12);
}
.app-launcher-icon {
  position: relative;
  width: 72px;
  height: 72px;
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  isolation: isolate;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.12);
}
.app-launcher-icon::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  z-index: 0;
}
.app-launcher-icon svg {
  position: relative;
  z-index: 1;
  width: 38px;
  height: 38px;
  display: block;
}
.app-launcher-icon--kitten::before {
  background: linear-gradient(145deg, #fb923c 0%, #f97316 48%, #ea580c 100%);
}
.app-launcher-icon--qclaw::before {
  background: linear-gradient(145deg, #f87171 0%, #ef4444 48%, #dc2626 100%);
}
.app-launcher-icon--brain::before {
  background: linear-gradient(145deg, #a78bfa 0%, #8b5cf6 48%, #7c3aed 100%);
}
.app-launcher-icon--store::before {
  background: linear-gradient(145deg, #60a5fa 0%, #3b82f6 48%, #1d4ed8 100%);
}
.app-launcher-name {
  font-size: 17px;
  font-weight: 700;
  color: #1e293b;
}
.app-launcher-desc {
  font-size: 13px;
  line-height: 1.55;
  color: #64748b;
  text-align: center;
}
.qclaw-shell {
  flex: 1;
  background: #f8fafc;
  color: #1f2937;
  padding: 16px;
  overflow: auto;
}
.qclaw-header {
  display: grid;
  grid-template-columns: 150px 1fr 100px;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.qclaw-title { font-size: 17px; font-weight: 700; text-align: center; letter-spacing: 0.2px; }
.qclaw-back, .qclaw-refresh {
  border: 1px solid #d1d5db;
  background: #ffffff;
  color: #374151;
  border-radius: 8px;
  padding: 8px 10px;
  cursor: pointer;
}
.qclaw-back:hover, .qclaw-refresh:hover {
  background: #f3f4f6;
}
.qclaw-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  align-items: start;
}
.qclaw-card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 14px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}
.qclaw-card h3 { margin: 0 0 12px; font-size: 14px; color: #111827; }
.qclaw-switch-row { display: flex; align-items: center; gap: 8px; }
.qclaw-route-list, .qclaw-test-list { display: grid; gap: 8px; max-height: 240px; overflow: auto; }
.qclaw-route-item { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.qclaw-route-item code { color: #4b5563; }
.qclaw-actions { margin-bottom: 10px; }
.qclaw-test-item {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 6px 8px;
  background: #f9fafb;
}
.qclaw-test-item .route-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #374151;
}
.qclaw-test-item .ok { color: #4ade80; }
.qclaw-test-item .fail { color: #f87171; }
.qclaw-openclaw-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  margin-bottom: 8px;
  align-items: center;
}
.qclaw-openclaw-row > .qclaw-input {
  min-width: 0;
}
.qclaw-openclaw-row-auth {
  grid-template-columns: auto auto 1fr auto;
  align-items: center;
}
.qclaw-ws-device-callout {
  margin: 0 0 12px;
  padding: 10px 12px;
  font-size: 11px;
  line-height: 1.5;
  color: #713f12;
  background: #fffbeb;
  border: 1px solid #fcd34d;
  border-radius: 8px;
}
.qclaw-ws-device-callout code {
  font-size: 10px;
  background: #fef3c7;
  padding: 1px 4px;
  border-radius: 4px;
}
.qclaw-ws-auth-hint {
  margin: 0 0 10px;
  font-size: 11px;
  line-height: 1.45;
  color: #4b5563;
}
.qclaw-ws-auth-hint code {
  font-size: 10px;
  background: #f3f4f6;
  padding: 1px 4px;
  border-radius: 4px;
  color: #374151;
}
.qclaw-ws-details {
  margin-bottom: 10px;
  font-size: 12px;
  color: #374151;
}
.qclaw-ws-details summary {
  cursor: pointer;
  color: #111827;
  font-weight: 600;
}
.qclaw-pre {
  margin: 6px 0 10px;
  padding: 8px 10px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 11px;
  line-height: 1.4;
  overflow-x: auto;
  white-space: pre-wrap;
  color: #1f2937;
}
.qclaw-ws-auth-label {
  font-size: 12px;
  color: #374151;
  white-space: nowrap;
}
.qclaw-select {
  background: #ffffff;
  border: 1px solid #d1d5db;
  color: #111827;
  border-radius: 8px;
  padding: 6px 8px;
  font-size: 12px;
  max-width: 220px;
}
.qclaw-input-grow {
  min-width: 0;
}
.qclaw-input {
  background: #ffffff;
  border: 1px solid #d1d5db;
  color: #111827;
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 12px;
}
.qclaw-openclaw-result {
  font-size: 12px;
  color: #4b5563;
  min-height: 18px;
  white-space: pre-wrap;
}
.qclaw-ws-reply {
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #14532d;
}
.qclaw-inline-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
  position: relative;
  z-index: 1;
}
.qclaw-ws-log {
  margin-top: 8px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f9fafb;
  padding: 8px;
  max-height: 120px;
  overflow: auto;
  font-size: 12px;
  color: #374151;
}
.qclaw-hint {
  font-size: 11px;
  color: #6b7280;
  align-self: center;
}
@media (max-width: 1180px) {
  .qclaw-grid {
    grid-template-columns: 1fr;
  }
  .qclaw-header {
    grid-template-columns: 1fr;
  }
  .qclaw-title {
    text-align: left;
  }
  .qclaw-openclaw-row-auth {
    grid-template-columns: 1fr;
  }
  .qclaw-select {
    max-width: none;
  }
}
</style>
