          <span class="app-launcher-icon" aria-hidden="true">�?��</span>
          <span class="app-launcher-name">�??工�??�?</span>
          <span class="app-launcher-desc">MOD �?��?浏�?�?��?�?�?�?��?� .xcmod �?��?</span>
        </button>
      </div>
    </div>

    <KittenAnalyzerView v-else-if="activeApp === 'kitten'" @back="exitAnalyzer" />

    <template v-else>
      <div class="qclaw-shell">
        <div class="qclaw-header">
          <button class="qclaw-back" type="button" @click="exitAnalyzer">�?�??�?�?��??表</button>
          <div class="qclaw-title">Qclaw�?�?��??�??· 路�?��?度面板</div>
          <button class="qclaw-refresh" type="button" @click="loadQclawPanel">�?��?�</button>
        </div>

        <div class="qclaw-grid">
          <section class="qclaw-card">
            <h3>微信�?�?��?�?��?�??/h3>
            <label class="qclaw-switch-row">
              <input type="checkbox" :checked="qclawWechatOpen" @change="toggleQclawWechat($event)">
              <span>{{ qclawWechatOpen ? '已�?�?? : '已�?��?? }}</span>
            </label>
          </section>

          <section class="qclaw-card">
            <h3>路�?��?�名�?可�?�??</h3>
            <div class="qclaw-route-list">
              <label v-for="route in qclawRoutes" :key="route.path" class="qclaw-route-item">
                <input type="checkbox" :checked="route.enabled" @change="toggleWhitelistRoute(route.path, $event)">
                <code>{{ route.path }}</code>
              </label>
            </div>
          </section>

          <section class="qclaw-card">
            <h3>�?�?��?�?�?路�?�</h3>
            <div class="qclaw-actions">
              <button class="btn btn-primary btn-sm" type="button" :disabled="qclawTesting" @click="testAllRoutes">
                {{ qclawTesting ? '�?�?�?..' : '�?�?�?��?�已启�?�路�?? }}
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
            <h3>OpenClaw �?�?</h3>
            <div class="qclaw-openclaw-row">
              <input v-model="openclawBase" class="qclaw-input" placeholder="http://localhost:28789">
              <button class="btn btn-secondary btn-sm" type="button" @click="saveOpenclawBase">保�?</button>
            </div>
            <div class="qclaw-openclaw-row">
              <input v-model="openclawMessage" class="qclaw-input" placeholder="�?�?�要�?�?OpenClaw �??�?�?>
              <button class="btn btn-primary btn-sm" type="button" :disabled="openclawSending" @click="sendToOpenclaw">
                {{ openclawSending ? '�?�?�中...' : '�?�?? }}
              </button>
            </div>
            <div class="qclaw-openclaw-result">{{ openclawResult || '�?�?�?�??..' }}</div>
          </section>

          <section class="qclaw-card">
            <h3>OpenClaw WebSocket 流式�?�?</h3>
            <div class="qclaw-ws-device-callout">
              握�??�??<code>CONTROL_UI_DEVICE_IDENTITY_REQUIRED</code> /�??control ui requires device identity�?��?��?提示�??�?strong>容�??误导</strong>�?�?�?��?�??�?�?��??�??
              <code>gateway.controlUi.allowInsecureAuth === true</code> <strong>�?/strong> TCP 被�?��?为<strong>�?��?��?��?</strong>�?code>isLocalClient</code>�?�?�?浏�?�?��?�否 Secure Context 不�?��?�??�?�??
              <br><br>
              <strong>�?�?� �??/strong> �??strong>正�?��?�?�?��??�?�台�?�子</strong>�?�?��?
              <code>openclaw config get gateway.controlUi.allowInsecureAuth</code>�?须�?<code>true</code>�?否�??
              <code>openclaw config set gateway.controlUi.allowInsecureAuth true</code> �?<code>openclaw gateway restart</code>�?�??�??�??�?��?��?��?��?�??�??<code>openclaw.json</code>�?不�??XCAGI �?�?�?�??
              <br>
              <strong>�?�?� �??/strong> WebSocket �??<code>ws://localhost:端口/ws</code>�?�?��?��?�??�? IP�??
              <br>
              <strong>常见�?�??/strong> �?�?��?�?� <strong>Docker / WSL 端口�?��?</strong> �?��?容�?��??�??�?��??源�?��?�?strong>不�?�</strong> 127.0.0.1�?code>isLocalClient</code> �?为 false�??�??即使�?� <code>localhost</code> �?�?�?样�?��??�??可�?��?�容�?� host �?�?�?��??�??�?�?��??档�?�?
              <code>gateway.allowRealIpFallback</code> / 可信代�?�?仍不�?�?��?�?�?可临�??
              <code>openclaw config set gateway.controlUi.dangerouslyDisableDeviceAuth true</code>�?�?�?��?��?�?��?�?��?请�?��?�??
            </div>
            <p class="qclaw-ws-auth-hint">
              <strong>token</strong>�?�?��?�?�填�??�?�?�?��?�?��??�?�享�?�?��?对�?�?��?�?�??
              <code>OPENCLAW_GATEWAY_TOKEN</code>�?协议�??�?<code>connect.params.auth.token</code>�?�??误码�??常�??�? AUTH_TOKEN�?�??
              <strong>password</strong>�?�?�?�?�认证�?�为�??�?码�?��?请�?�?�?�?
              <code>auth.password</code>�?对�?<code>OPENCLAW_GATEWAY_PASSWORD</code>�??
              不确�?�?�?��?�?�模式�?��?��?端�?��?�?
              <code>openclaw config get gateway.auth.mode</code>
            </p>
            <details class="qclaw-ws-details">
              <summary>�?��?� UI / 设�?身份�?�?��?A�?�?�荐�?�?�?��?B</summary>
              <p class="qclaw-ws-auth-hint">
                �?��?��??UI �??WebSocket �?�设�?校�?失败�?可�?� <strong>�?��? A</strong>�?�? <code>dangerouslyDisableDeviceAuth</code> �?��?�?��?�?
              </p>
              <pre class="qclaw-pre">openclaw config get gateway.controlUi.allowInsecureAuth
openclaw config set gateway.controlUi.dangerouslyDisableDeviceAuth false
openclaw config set gateway.controlUi.allowInsecureAuth true
openclaw gateway restart</pre>
              <p class="qclaw-ws-auth-hint">
                <strong>�?��? B�?�??�?�?��?/strong>�?�?�?PyNaCl 并�?�客�?�端�??�?�?�要�?�?�?�设�?签名�?code>pip install pynacl</code>�?�?��??�??档�?�??Ed25519 签名�?�??
              </p>
              <p class="qclaw-ws-auth-hint">
                QClaw �?�带�??<code>openclaw.json</code> 模板已�?�?<code>allowInsecureAuth: true</code>�??code>dangerouslyDisableDeviceAuth: false</code>�?�?�你使�?��?��?��?��?�?�??�?�置�?请�?��?面�?�令�?步�??
              </p>
              <p class="qclaw-ws-auth-hint">
                �?�?使�?� <code>openclaw-control-ui</code> 身份以保�??<code>operator.write</code>�?�?�握�??�??<code>origin not allowed</code>�?请�??
                <code>gateway.controlUi.allowedOrigins</code> 中�?��?�你访�?� XCAGI �??页面来源�?�?�? <code>http://localhost:5000</code>�?�??
              </p>
            </details>
            <div class="qclaw-openclaw-row qclaw-openclaw-row-auth">
              <label class="qclaw-ws-auth-label">认证</label>
              <select v-model="openclawWsAuthMode" class="qclaw-select">
                <option value="token">token�?OPENCLAW_GATEWAY_TOKEN�?/option>
                <option value="password">password�?OPENCLAW_GATEWAY_PASSWORD�?/option>
              </select>
              <input
                v-model="openclawGatewayToken"
                class="qclaw-input qclaw-input-grow"
                :type="openclawWsAuthMode === 'password' ? 'password' : 'text'"
                :placeholder="openclawWsAuthMode === 'password' ? '�?�?��?码�?auth.password�? : '�?�?� Token�?auth.token�?"
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
                  �?�为 localhost
                </button>
                <button class="btn btn-secondary btn-sm" type="button" :disabled="wsConnected || wsConnecting" @click="connectOpenclawWs">
                  {{ wsConnecting ? '�?�?��?..' : '�?�?�' }}
                </button>
                <button class="btn btn-secondary btn-sm" type="button" :disabled="!wsConnected" @click="disconnectOpenclawWs">
                  �?��?
                </button>
              </div>
            </div>
            <div class="qclaw-openclaw-row">
              <input v-model="openclawWsSessionKey" class="qclaw-input" placeholder="sessionKey�?�? main�?须为�?�?�已�??�?话�?">
              <span class="qclaw-hint">�?�?� schema 要�? sessionKey + idempotencyKey�?面板已�?��?��??�?��?�??�?</span>
            </div>
            <p class="qclaw-ws-auth-hint">
              �?�令�?可�?�??�?�?�??可运�?�??�?��?<code>scripts/openclaw_ws_chat_example.py</code>�?�?�?�?��?�?�协议对齐�?含正确 <code>connect</code> �?<code>event: chat</code>�?�??
            </p>
            <div class="qclaw-openclaw-row">
              <input v-model="openclawWsMessage" class="qclaw-input" placeholder="�?息正�??">
              <button class="btn btn-primary btn-sm" type="button" :disabled="!wsConnected" @click="sendOpenclawWsMessage">
                �?�??
              </button>
            </div>
            <div class="qclaw-openclaw-result">{{ wsStatusText }}</div>
            <div v-if="wsReplyPreview" class="qclaw-openclaw-result qclaw-ws-reply">�?��??�?{{ wsReplyPreview }}</div>
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
/** 须�??�?�?�?�中已�?�?��??�?话�?�?�?main */
const openclawWsSessionKey = ref('main')
const openclawWsMessage = ref('你好')
/** token �??connect.params.auth.token�?password �??auth.password�?�? gateway.auth.mode �?�?��? */
const openclawWsAuthMode = ref('token')
const openclawGatewayToken = ref('')
const wsConnected = ref(false)
const wsConnecting = ref(false)
const wsStatusText = ref('???')
/** �?�?� event:chat �?��?��??�?��??�??�?��?�? chat.progress�?*/
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
    openclawResult.value = '加载面板失败'
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
  openclawResult.value = result.ok ? 'OpenClaw 基址已保存' : result.message
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
      openclawResult.value = `�?��??�?{show}`
    } else {
      openclawResult.value = `失败�?{result.message || '�?��?��??误'}`
    }
  } catch (err) {
    const errMessage = err && err.message ? err.message : err
    openclawResult.value = `失败�?{errMessage}`
  } finally {
    openclawSending.value = false
  }
}

const normalizeOpenclawWsToLoopback = () => {
  const s = String(openclawWsUrl.value || '').trim()
  if (!s) {
    openclawWsUrl.value = 'ws://localhost:28789/ws'
    wsStatusText.value = '已填�?��?�?ws://localhost:28789/ws'
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
    wsStatusText.value = '已�?��?��?��??�?��?��?�?�?��??修�?�'
  } else {
    wsStatusText.value = `已�?��? ${next}`
  }
}

const connectOpenclawWs = () => {
  if (wsConnected.value || wsConnecting.value) return
  wsConnecting.value = true
  wsStatusText.value = '�?�?��?..'
  wsLogs.value = []
  wsReplyPreview.value = ''
  try {
    const wsUrl = String(openclawWsUrl.value || '').trim()
    try {
      const u = new URL(wsUrl)
      const h = String(u.hostname || '').toLowerCase()
      const loopbackHost = h === 'localhost' || h === '127.0.0.1' || h === '[::1]'
      if (!loopbackHost) {
        pushWsLog('[warn] WS 主�?��?�?��?��??�?��?建议�??ws://localhost:端口/ws�?避�?�握�??失败�??)
      }
    } catch (_ignore) {
      // ignore
    }

    wsClient = new WebSocket(wsUrl)
    wsClient.onopen = () => {
      wsConnecting.value = false
      wsStatusText.value = '已建�?�?�?��?�?�? challenge...'
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
        wsStatusText.value = '认证�??�?�?已�?�?�'
        pushWsLog('[auth] hello-ok')
        return
      }

      if (msgType === 'res' && msg && msg.ok === false && msgError) {
        const isChatAck = Boolean(wsLastChatReqId && msg.id === wsLastChatReqId)
        if (!isChatAck) {
          const dcode = msgError.details && msgError.details.code
          if (dcode === 'CONTROL_UI_DEVICE_IDENTITY_REQUIRED') {
            pushWsLog('[hint] 请�?�??allowInsecureAuth=true �?�?�?��?�启�??�??�??)
            pushWsLog('[hint] 请使�??ws://localhost:端口/ws�?避�?��?�?��?��?�?�?��?��??)
            wsStatusText.value = '握�??失败�?Control UI 设�?身份校�?�?��??�?'
          } else {
            wsStatusText.value = `握�??失败: ${msgError.message || dcode || 'unknown'}`
          }
          pushWsLog(`[res error] ${msgError.message || JSON.stringify(msgError)}`)
          return
        }
      }

      if (msgType === 'res' && wsLastChatReqId && msg && msg.id === wsLastChatReqId) {
        if (msg.ok) {
          pushWsLog(`[chat.send] 已�?��?${JSON.stringify(msgPayload || {})}`)
          wsStatusText.value = '已�?�?��?�?�?模�??�??复�??
        } else {
          const errMsg = msgError.message || JSON.stringify(msgError || {})
          pushWsLog(`[chat.send] 失败 ${errMsg}`)
          wsStatusText.value = `�?�?�失�? ${errMsg}`
        }
        return
      }

      if (msgType === 'event' && msgEvent === 'chat') {
        if (msgPayload.state === 'error') {
          const em = msgPayload.errorMessage || 'unknown'
          pushWsLog(`[chat error] ${em}`)
          wsReplyPreview.value = ''
          wsStatusText.value = `对话�??误: ${em}`
          return
        }
        const text = extractAssistantTextFromChatPayload(msgPayload)
        if (text) {
          wsReplyPreview.value = text
          wsStatusText.value = msgPayload.state === 'final' ? '�??复�?�?�' : '模�??�?�?�中�??
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

      pushWsLog(raw.length > 600 ? `[message] ${raw.slice(0, 600)}�?�` : `[message] ${raw}`)
    }

    wsClient.onerror = () => {
      wsStatusText.value = '�?�?��?常'
      pushWsLog('[error] websocket error')
    }
    wsClient.onclose = () => {
      wsConnecting.value = false
      wsConnected.value = false
      wsStatusText.value = '已�?��?'
      pushWsLog('[close] websocket closed')
      wsClient = null
    }
  } catch (err) {
    wsConnecting.value = false
    wsConnected.value = false
    wsStatusText.value = `�?�?�失败: ${err && err.message ? err.message : err}`
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
    wsStatusText.value = openclawWsAuthMode.value === 'password' ? '缺�? Gateway �?码' : '缺�? Gateway Token'
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
  // OpenClaw�?�?� device �?��? Control UI 客�?�端�?保�?? scopes�?cli + token �?被 clearUnboundScopes �?空导�?� chat.send �??missing scope: operator.write�??
  // 使�?� openclaw-control-ui + ui�?�?�?�?��?��?�面�?�?��?并�?� allowInsecureAuth + �?��?�访�?��?保�??operator �?�?��??�??
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
  gap: 16px;
  background: #f8fafc;
}
.ecosystem-home-title {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}
.launcher-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 240px));
  gap: 18px;
}
.app-launcher {
  width: 240px;
  border: 1px solid #dbeafe;
  background: #ffffff;
  border-radius: 16px;
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  box-shadow: 0 10px 24px rgba(30, 64, 175, 0.08);
}
.app-launcher:hover {
  transform: translateY(-2px);
  box-shadow: 0 14px 28px rgba(30, 64, 175, 0.12);
}
.app-launcher-icon {
  width: 88px;
  height: 88px;
  border-radius: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 42px;
  background: linear-gradient(135deg, #dbeafe, #bfdbfe);
}
.app-launcher-name {
  font-size: 18px;
  font-weight: 700;
  color: #1e3a8a;
}
.app-launcher-desc {
  font-size: 13px;
  color: #64748b;
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

