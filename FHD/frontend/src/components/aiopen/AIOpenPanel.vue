<template>
  <div class="aiopen-shell">
    <div class="aiopen-header">
      <button class="aiopen-back" type="button" @click="$emit('back')">返回应用列表</button>
      <div class="aiopen-title">AIOPEN 开放智控 · 我是 AI 的工具</div>
      <button class="aiopen-refresh" type="button" @click="loadPanel">刷新</button>
    </div>

    <div class="aiopen-grid">
      <!-- ① 接入信息 -->
      <section class="aiopen-card">
        <h3>接入信息（MCP / API）</h3>
        <div class="aiopen-endpoint-row">
          <span class="aiopen-endpoint-label">MCP</span>
          <code class="aiopen-endpoint-code">{{ mcpUrl }}</code>
          <button class="btn btn-secondary btn-sm" type="button" @click="copyText(mcpUrl)">复制</button>
        </div>
        <div class="aiopen-endpoint-row">
          <span class="aiopen-endpoint-label">REST</span>
          <code class="aiopen-endpoint-code">POST {{ invokeUrl }}</code>
          <button class="btn btn-secondary btn-sm" type="button" @click="copyText(invokeUrl)">复制</button>
        </div>
        <div class="aiopen-keys">
          <div class="aiopen-keys-head">
            <span>API Key（请求头 X-AIOPEN-Key）</span>
            <button class="btn btn-primary btn-sm" type="button" @click="createKey">生成 Key</button>
          </div>
          <div v-if="newKey" class="aiopen-new-key">
            <code>{{ newKey }}</code>
            <button class="btn btn-secondary btn-sm" type="button" @click="copyText(newKey)">复制</button>
            <span class="aiopen-hint">仅本次展示，请立即保存</span>
          </div>
          <div class="aiopen-key-list">
            <div v-for="k in keys" :key="k.key_preview" class="aiopen-key-item">
              <code>{{ k.key_preview }}</code>
              <span>{{ k.label }}</span>
            </div>
            <div v-if="!keys.length" class="aiopen-hint">未配置 Key（开发模式直通；生产请设 AIOPEN_API_KEY 或生成运行时 Key）</div>
          </div>
        </div>
        <details class="aiopen-details">
          <summary>Cursor / Claude mcp.json 配置示例</summary>
          <pre class="aiopen-pre">{{ mcpJsonExample }}</pre>
        </details>
        <details class="aiopen-details">
          <summary>curl 调用示例</summary>
          <pre class="aiopen-pre">{{ curlExample }}</pre>
        </details>
        <div class="aiopen-result">{{ accessResult }}</div>
      </section>

      <!-- ② 工具目录 + 白名单 -->
      <section class="aiopen-card">
        <h3>工具目录与路由白名单</h3>
        <div class="aiopen-tools">
          <div v-for="tool in manifestTools" :key="tool.name" class="aiopen-tool-item">
            <code>{{ tool.name }}</code>
            <span>{{ tool.description }}</span>
          </div>
        </div>
        <h4 class="aiopen-subhead">api_call 白名单</h4>
        <div class="aiopen-route-list">
          <label v-for="route in routes" :key="route.path" class="aiopen-route-item">
            <input type="checkbox" :checked="route.enabled" @change="toggleWhitelist(route.path, $event)">
            <code>{{ route.path }}</code>
          </label>
        </div>
      </section>

      <!-- ③ 虚拟光标会话 -->
      <section class="aiopen-card">
        <h3>虚拟光标 · AI 模拟操作</h3>
        <label class="aiopen-switch-row">
          <input type="checkbox" :checked="remoteControlEnabled" @change="toggleRemoteControl($event)">
          <span>远程操控总开关（服务端）：{{ remoteControlEnabled ? '已开启' : '已关闭' }}</span>
        </label>
        <label class="aiopen-switch-row">
          <input type="checkbox" :checked="cursorEnabled" @change="toggleScreenSession($event)">
          <span>本浏览器作为受控屏幕：{{ cursorConnected ? `已连接（${cursorSessionId}）` : (cursorEnabled ? '连接中…' : '未开启') }}</span>
        </label>
        <div class="aiopen-hint">开启后，外部 AI Agent 可经 ui_snapshot / ui_click / ui_type 等工具以虚拟光标操作本页面。</div>
        <h4 class="aiopen-subhead">在线 screen 会话（{{ screenSessions.length }}）</h4>
        <div class="aiopen-key-list">
          <div v-for="s in screenSessions" :key="s.session_id" class="aiopen-key-item">
            <code>{{ s.session_id }}</code>
            <span>{{ s.label || '' }}</span>
          </div>
          <div v-if="!screenSessions.length" class="aiopen-hint">暂无在线会话</div>
        </div>
        <h4 class="aiopen-subhead">最近指令</h4>
        <div class="aiopen-log">
          <div v-for="(cmd, idx) in recentCommands" :key="idx">{{ formatCommand(cmd) }}</div>
          <div v-for="(line, idx) in cursorLogs.slice(-10)" :key="'local-' + idx">{{ line }}</div>
        </div>
      </section>

      <!-- ④ 微信开放权限开关（沿用） -->
      <section class="aiopen-card">
        <h3>微信开放权限开关</h3>
        <label class="aiopen-switch-row">
          <input type="checkbox" :checked="wechatOpen" @change="toggleWechat($event)">
          <span>{{ wechatOpen ? '已开放' : '已关闭' }}</span>
        </label>
      </section>

      <!-- ⑤ OpenClaw HTTP 联调（沿用） -->
      <section class="aiopen-card">
        <h3>外部网关联调（OpenClaw HTTP）</h3>
        <div class="aiopen-row">
          <input v-model="openclawBase" class="aiopen-input" placeholder="http://localhost:28789">
          <button class="btn btn-secondary btn-sm" type="button" @click="saveOpenclawBase">保存</button>
        </div>
        <div class="aiopen-row">
          <input v-model="openclawMessage" class="aiopen-input" placeholder="输入要发给 OpenClaw 的消息">
          <button class="btn btn-primary btn-sm" type="button" :disabled="openclawSending" @click="sendToOpenclaw">
            {{ openclawSending ? '发送中...' : '发送' }}
          </button>
        </div>
        <div class="aiopen-result">{{ openclawResult || '等待发送...' }}</div>
      </section>

      <!-- ⑥ OpenClaw WebSocket 流式联调（沿用） -->
      <section class="aiopen-card">
        <h3>外部网关联调（OpenClaw WebSocket 流式）</h3>
        <div class="aiopen-ws-device-callout">
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
        <p class="aiopen-ws-auth-hint">
          <strong>token</strong>：在下方填写与网关一致的共享密钥，对应环境变量
          <code>OPENCLAW_GATEWAY_TOKEN</code>（协议里为 <code>connect.params.auth.token</code>，错误码里常写作 AUTH_TOKEN）。
          <strong>password</strong>：将下方认证改为「密码」，请求体会发
          <code>auth.password</code>，对应 <code>OPENCLAW_GATEWAY_PASSWORD</code>。
          不确定网关当前模式时在终端执行：
          <code>openclaw config get gateway.auth.mode</code>
        </p>
        <details class="aiopen-ws-details">
          <summary>控制 UI / 设备身份：方案 A（推荐）与方案 B</summary>
          <p class="aiopen-ws-auth-hint">
            若控制 UI 或 WebSocket 因设备校验失败，可用 <strong>方案 A</strong>（比 <code>dangerouslyDisableDeviceAuth</code> 更安全）：
          </p>
          <pre class="aiopen-pre">openclaw config get gateway.controlUi.allowInsecureAuth
openclaw config set gateway.controlUi.dangerouslyDisableDeviceAuth false
openclaw config set gateway.controlUi.allowInsecureAuth true
openclaw gateway restart</pre>
          <p class="aiopen-ws-auth-hint">
            <strong>方案 B（最安全）</strong>：安装 PyNaCl 并在客户端按网关要求完成设备签名：<code>pip install pynacl</code>（再按文档实现 Ed25519 签名）。
          </p>
          <p class="aiopen-ws-auth-hint">
            QClaw 自带的 <code>openclaw.json</code> 模板已默认 <code>allowInsecureAuth: true</code>、<code>dangerouslyDisableDeviceAuth: false</code>；若你使用用户目录下的配置，请用上面命令同步。
          </p>
          <p class="aiopen-ws-auth-hint">
            联调使用 <code>openclaw-control-ui</code> 身份以保留 <code>operator.write</code>；若握手报 <code>origin not allowed</code>，请在
            <code>gateway.controlUi.allowedOrigins</code> 中加入你访问 XCAGI 的页面来源（例如 <code>http://localhost:5000</code>）。
          </p>
        </details>
        <div class="aiopen-row aiopen-row-auth">
          <label class="aiopen-ws-auth-label">认证</label>
          <select v-model="openclawWsAuthMode" class="aiopen-select">
            <option value="token">token（OPENCLAW_GATEWAY_TOKEN）</option>
            <option value="password">password（OPENCLAW_GATEWAY_PASSWORD）</option>
          </select>
          <input
            v-model="openclawGatewayToken"
            class="aiopen-input aiopen-input-grow"
            :type="openclawWsAuthMode === 'password' ? 'password' : 'text'"
            :placeholder="openclawWsAuthMode === 'password' ? '网关密码（auth.password）' : '网关 Token（auth.token）'"
          >
          <span class="aiopen-hint">Challenge-Response</span>
        </div>
        <div class="aiopen-row">
          <input v-model="openclawWsUrl" class="aiopen-input" placeholder="ws://localhost:28789/ws">
          <div class="aiopen-inline-actions">
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
        <div class="aiopen-row">
          <input v-model="openclawWsSessionKey" class="aiopen-input" placeholder="sessionKey（如 main，须为网关已有会话）">
          <span class="aiopen-hint">网关 schema 要求 sessionKey + idempotencyKey（面板已自动生成后者）</span>
        </div>
        <p class="aiopen-ws-auth-hint">
          命令行可参考仓库内可运行脚本：<code>scripts/openclaw_ws_chat_example.py</code>（与当前网关协议对齐，含正确 <code>connect</code> 与 <code>event: chat</code>）。
        </p>
        <div class="aiopen-row">
          <input v-model="openclawWsMessage" class="aiopen-input" placeholder="消息正文">
          <button class="btn btn-primary btn-sm" type="button" :disabled="!wsConnected" @click="sendOpenclawWsMessage">
            发送
          </button>
        </div>
        <div class="aiopen-result">{{ wsStatusText }}</div>
        <div v-if="wsReplyPreview" class="aiopen-result aiopen-ws-reply">助手：{{ wsReplyPreview }}</div>
        <div class="aiopen-ws-log">
          <div v-for="(line, idx) in wsLogs" :key="idx">{{ line }}</div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { safeJsonRequest } from '@/utils/safeJsonRequest'
import { getApiBase } from '@/utils/apiBase'
import { useAiOpenCursor } from '@/composables/useAiOpenCursor'

defineEmits(['back'])

const {
  enabled: cursorEnabled,
  connected: cursorConnected,
  sessionId: cursorSessionId,
  logs: cursorLogs,
  setEnabled: setCursorEnabled,
} = useAiOpenCursor()

// ---- 面板状态 -------------------------------------------------------------

const wechatOpen = ref(false)
const routes = ref([])
const remoteControlEnabled = ref(false)
const screenSessions = ref([])
const recentCommands = ref([])
const keys = ref([])
const newKey = ref('')
const accessResult = ref('')
const manifestTools = ref([])

const openclawBase = ref('http://localhost:28789')
const openclawMessage = ref('你好')
const openclawSending = ref(false)
const openclawResult = ref('')

const apiOrigin = computed(() => {
  const base = getApiBase()
  if (base) return base
  return typeof window !== 'undefined' ? window.location.origin : ''
})
const mcpUrl = computed(() => `${apiOrigin.value}/api/aiopen/mcp`)
const invokeUrl = computed(() => `${apiOrigin.value}/api/aiopen/invoke`)

const mcpJsonExample = computed(() => JSON.stringify(
  {
    mcpServers: {
      xcagi_aiopen: {
        url: mcpUrl.value,
        headers: { 'X-AIOPEN-Key': '<你的 API Key>' }
      }
    }
  },
  null,
  2
))

const curlExample = computed(() => [
  `curl -X POST '${invokeUrl.value}' \\`,
  `  -H 'Content-Type: application/json' \\`,
  `  -H 'X-AIOPEN-Key: <你的 API Key>' \\`,
  `  -d '{"tool": "chat", "args": {"message": "你好"}}'`
].join('\n'))

const loadPanel = async () => {
  try {
    const result = await safeJsonRequest('/api/aiopen/panel')
    if (result.ok && result.data?.success) {
      wechatOpen.value = Boolean(result.data.wechat_open)
      routes.value = Array.isArray(result.data.routes) ? result.data.routes : []
      openclawBase.value = String(result.data.openclaw_base || 'http://localhost:28789')
      remoteControlEnabled.value = Boolean(result.data.remote_control_enabled)
      screenSessions.value = Array.isArray(result.data.screen_sessions) ? result.data.screen_sessions : []
      recentCommands.value = Array.isArray(result.data.recent_commands) ? result.data.recent_commands : []
      keys.value = Array.isArray(result.data.keys) ? result.data.keys : []
      openclawResult.value = ''
    } else {
      routes.value = []
      openclawResult.value = result.message || '加载面板失败'
    }
  } catch (_err) {
    routes.value = []
    openclawResult.value = '加载面板失败：网络异常'
  }
  try {
    const mf = await safeJsonRequest('/api/aiopen/manifest')
    if (mf.ok && mf.data?.success) {
      manifestTools.value = Array.isArray(mf.data.tools) ? mf.data.tools : []
    }
  } catch (_err) {
    manifestTools.value = []
  }
}

const copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
    accessResult.value = '已复制到剪贴板'
  } catch (_err) {
    accessResult.value = `复制失败，请手动复制：${text}`
  }
}

const createKey = async () => {
  const result = await safeJsonRequest('/api/aiopen/keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label: '面板生成' })
  })
  if (result.ok && result.data?.success) {
    newKey.value = String(result.data.key || '')
    accessResult.value = '已生成新 Key（仅本次展示）'
    await loadPanel()
  } else {
    accessResult.value = result.message || '生成失败'
  }
}

const toggleWhitelist = async (path, event) => {
  const enabled = Boolean(event?.target?.checked)
  routes.value = routes.value.map((item) => item.path === path ? { ...item, enabled } : item)
  const result = await safeJsonRequest('/api/aiopen/whitelist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, enabled })
  })
  if (!result.ok) {
    openclawResult.value = result.message
  }
}

const toggleWechat = async (event) => {
  const enabled = Boolean(event?.target?.checked)
  wechatOpen.value = enabled
  const result = await safeJsonRequest('/api/ai/qclaw/wechat-gateway', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled })
  })
  if (!result.ok) {
    openclawResult.value = result.message
  }
}

const toggleRemoteControl = async (event) => {
  const enabled = Boolean(event?.target?.checked)
  remoteControlEnabled.value = enabled
  const result = await safeJsonRequest('/api/aiopen/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled })
  })
  if (!result.ok) {
    openclawResult.value = result.message
  }
}

const toggleScreenSession = (event) => {
  setCursorEnabled(Boolean(event?.target?.checked))
}

const formatCommand = (cmd) => {
  const ts = cmd?.ts ? new Date(cmd.ts * 1000).toLocaleTimeString('zh-CN', { hour12: false }) : ''
  return `[${ts}] ${cmd?.action || '?'} → ${cmd?.session_id || '?'}`
}

// ---- OpenClaw HTTP 联调 -----------------------------------------------------

const saveOpenclawBase = async () => {
  const result = await safeJsonRequest('/api/aiopen/config', {
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
    const result = await safeJsonRequest('/api/aiopen/openclaw/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: openclawMessage.value, source: 'aiopen' })
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

// ---- OpenClaw WebSocket 流式联调 ---------------------------------------------

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
      userAgent: 'xcagi-aiopen/1.0'
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

onMounted(loadPanel)

onBeforeUnmount(() => {
  if (wsClient) {
    wsClient.close()
    wsClient = null
  }
})
</script>

<style scoped>
.aiopen-shell {
  flex: 1;
  background: #f8fafc;
  color: #1f2937;
  padding: 16px;
  overflow: auto;
}
.aiopen-header {
  display: grid;
  grid-template-columns: 150px 1fr 100px;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.aiopen-title { font-size: 17px; font-weight: 700; text-align: center; letter-spacing: 0.2px; }
.aiopen-back, .aiopen-refresh {
  border: 1px solid #d1d5db;
  background: #ffffff;
  color: #374151;
  border-radius: 8px;
  padding: 8px 10px;
  cursor: pointer;
}
.aiopen-back:hover, .aiopen-refresh:hover {
  background: #f3f4f6;
}
.aiopen-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  align-items: start;
}
.aiopen-card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 14px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}
.aiopen-card h3 { margin: 0 0 12px; font-size: 14px; color: #111827; }
.aiopen-subhead { margin: 12px 0 8px; font-size: 12px; color: #374151; }
.aiopen-switch-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 13px; }
.aiopen-route-list { display: grid; gap: 8px; max-height: 240px; overflow: auto; }
.aiopen-route-item { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.aiopen-route-item code { color: #4b5563; }
.aiopen-endpoint-row {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.aiopen-endpoint-label { font-size: 11px; font-weight: 700; color: #1d4ed8; }
.aiopen-endpoint-code {
  font-size: 11px;
  background: #f3f4f6;
  border-radius: 6px;
  padding: 5px 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #374151;
}
.aiopen-keys { margin-top: 10px; }
.aiopen-keys-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: #374151;
  margin-bottom: 8px;
}
.aiopen-new-key {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  padding: 6px 8px;
  margin-bottom: 8px;
}
.aiopen-new-key code { font-size: 11px; color: #14532d; word-break: break-all; }
.aiopen-key-list { display: grid; gap: 6px; max-height: 140px; overflow: auto; }
.aiopen-key-item {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 5px 8px;
  background: #f9fafb;
  color: #374151;
}
.aiopen-tools { display: grid; gap: 6px; max-height: 220px; overflow: auto; }
.aiopen-tool-item {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  gap: 8px;
  font-size: 11px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 5px 8px;
  background: #f9fafb;
  color: #4b5563;
}
.aiopen-tool-item code { color: #1d4ed8; font-weight: 600; }
.aiopen-log {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f9fafb;
  padding: 8px;
  max-height: 130px;
  overflow: auto;
  font-size: 11px;
  color: #374151;
  display: grid;
  gap: 3px;
}
.aiopen-details {
  margin: 8px 0;
  font-size: 12px;
  color: #374151;
}
.aiopen-details summary {
  cursor: pointer;
  color: #111827;
  font-weight: 600;
}
.aiopen-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  margin-bottom: 8px;
  align-items: center;
}
.aiopen-row > .aiopen-input {
  min-width: 0;
}
.aiopen-row-auth {
  grid-template-columns: auto auto 1fr auto;
  align-items: center;
}
.aiopen-ws-device-callout {
  margin: 0 0 12px;
  padding: 10px 12px;
  font-size: 11px;
  line-height: 1.5;
  color: #713f12;
  background: #fffbeb;
  border: 1px solid #fcd34d;
  border-radius: 8px;
}
.aiopen-ws-device-callout code {
  font-size: 10px;
  background: #fef3c7;
  padding: 1px 4px;
  border-radius: 4px;
}
.aiopen-ws-auth-hint {
  margin: 0 0 10px;
  font-size: 11px;
  line-height: 1.45;
  color: #4b5563;
}
.aiopen-ws-auth-hint code {
  font-size: 10px;
  background: #f3f4f6;
  padding: 1px 4px;
  border-radius: 4px;
  color: #374151;
}
.aiopen-ws-details {
  margin-bottom: 10px;
  font-size: 12px;
  color: #374151;
}
.aiopen-ws-details summary {
  cursor: pointer;
  color: #111827;
  font-weight: 600;
}
.aiopen-pre {
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
.aiopen-ws-auth-label {
  font-size: 12px;
  color: #374151;
  white-space: nowrap;
}
.aiopen-select {
  background: #ffffff;
  border: 1px solid #d1d5db;
  color: #111827;
  border-radius: 8px;
  padding: 6px 8px;
  font-size: 12px;
  max-width: 220px;
}
.aiopen-input-grow {
  min-width: 0;
}
.aiopen-input {
  background: #ffffff;
  border: 1px solid #d1d5db;
  color: #111827;
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 12px;
}
.aiopen-result {
  font-size: 12px;
  color: #4b5563;
  min-height: 18px;
  white-space: pre-wrap;
}
.aiopen-ws-reply {
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #14532d;
}
.aiopen-inline-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
  position: relative;
  z-index: 1;
}
.aiopen-ws-log {
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
.aiopen-hint {
  font-size: 11px;
  color: #6b7280;
  align-self: center;
}
@media (max-width: 1180px) {
  .aiopen-grid {
    grid-template-columns: 1fr;
  }
  .aiopen-header {
    grid-template-columns: 1fr;
  }
  .aiopen-title {
    text-align: left;
  }
  .aiopen-row-auth {
    grid-template-columns: 1fr;
  }
  .aiopen-select {
    max-width: none;
  }
}
</style>
