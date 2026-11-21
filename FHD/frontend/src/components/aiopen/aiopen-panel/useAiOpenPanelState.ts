import { computed, ref } from 'vue'
import type { Ref } from 'vue'
import { getApiBase } from '@/utils/apiBase'
import {
  buildAiopenClientInstalls,
  resolveAiopenBackendBase,
} from '@/utils/aiopenMcpInstall'
import type { AiMcpClientInstall } from '@/utils/aiopenMcpInstall'

/** 白名单路由行（后端载荷宽松子集） */
export interface AiopenWhitelistRoute {
  path: string
  enabled: boolean
}

/** MCP manifest 工具行（后端载荷宽松子集） */
export interface AiopenManifestTool {
  name: string
  description?: string
}

/** /api/aiopen/panel 载荷（宽松子集） */
export interface AiopenPanelPayload {
  wechat_open?: boolean
  routes?: AiopenWhitelistRoute[]
  openclaw_base?: string
  remote_control_enabled?: boolean
  keys?: Array<Record<string, unknown>>
  client_mode?: boolean
  has_active_key?: boolean
}

/** /api/aiopen/manifest 载荷（宽松子集） */
export interface AiopenManifestPayload {
  success?: boolean
  name?: string
  tool_count?: number
  tools?: AiopenManifestTool[]
}

/** /api/aiopen/install 载荷（宽松子集） */
export interface AiopenInstallPayload {
  success?: boolean
  tool_count?: number
  server_name?: string
  mcp_url?: string
  methods?: {
    stdio?: { script_path?: string }
    url?: { config?: { url?: string } }
  }
  clients?: AiMcpClientInstall[]
}

export function useAiOpenPanelState(options: { cursorEnabled: Ref<boolean>; cursorConnected: Ref<boolean> }) {
  const { cursorEnabled, cursorConnected } = options

  const TOOL_LABELS: Record<string, { label: string; desc: string }> = {
    api_catalog: { label: '查看能力', desc: '列出当前账号可用的工具与员工' },
    operation_call: { label: '执行能力', desc: '按当前账号权限执行已登记的业务能力' },
    chat: { label: '对话', desc: '和 XCAGI AI 助手聊天' },
    capability_loop: { label: '闭环自检', desc: '核对可用能力、只读执行与任务回执' },
    ui_sessions: { label: '查看屏幕', desc: '有哪些浏览器正在待命' },
    ui_snapshot: { label: '看页面', desc: '读取当前页面上的按钮和输入框' },
    ui_navigate: { label: '跳转', desc: '打开指定菜单或页面' },
    ui_click: { label: '点击', desc: '用虚拟光标点击按钮' },
    ui_type: { label: '输入', desc: '在输入框里打字' },
    ui_scroll: { label: '滚动', desc: '滚动页面找到内容' },
  }

  const wechatOpen = ref(false)
  const routes = ref<AiopenWhitelistRoute[]>([])
  const remoteControlEnabled = ref(false)
  const keys = ref<Array<Record<string, unknown>>>([])
  const usage = ref<Record<string, unknown> | null>(null)
  const usageRecent = ref<Array<Record<string, unknown>>>([])
  const newKey = ref('')
  const accessResult = ref('')
  const panelError = ref('')
  const panelAvailable = ref(false)
  const clientMode = ref(false)
  const hasActiveClientKey = ref(false)
  const keyRunning = ref(false)
  const manifestTools = ref<AiopenManifestTool[]>([])
  const setupRunning = ref(false)
  const shutdownRunning = ref(false)
  const seedRunning = ref(false)
  const loopRunning = ref(false)
  const loopResultText = ref('')
  const installBundle = ref<AiopenInstallPayload | null>(null)
  const mcpHealthy = ref(false)
  const mcpHealthText = ref('')
  const installedClientIds = ref<string[]>([])
  const selectedClientId = ref('cursor')
  const stdioScriptPath = ref('')

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

  /**
   * 复制给外部 AI 的地址必须跟用户实际访问的地址一致：
   * 从局域网 / 域名打开时，后端 install 端点可能仍回 127.0.0.1，这里用页面主机名替换回环主机，
   * 本机访问（127.0.0.1 / localhost）则保持后端原地址与端口不变。
   */
  const reachableOrigin = computed(() => {
    const base = String(backendOrigin.value || '').replace(/\/$/, '')
    if (typeof window === 'undefined' || !base) return base
    const pageHost = String(window.location.hostname || '').toLowerCase()
    const loopback = new Set(['127.0.0.1', 'localhost', '::1'])
    if (!pageHost || loopback.has(pageHost)) return base
    try {
      const url = new URL(base)
      if (loopback.has(url.hostname.toLowerCase())) {
        url.hostname = pageHost
        return url.origin
      }
    } catch {
      /* 保持原地址 */
    }
    return base
  })

  const activeKey = computed(() => newKey.value || '')
  const hasConnectConfig = computed(() => Boolean(activeKey.value) || keys.value.length > 0)

  // 当前用户所在端的入口：管理端与主前端不同，用于「ui_sessions 为空」时的提示
  const consoleUrl = computed(() => {
    if (typeof window === 'undefined') return ''
    const isAdminConsole = String(import.meta.env.VITE_XCMAX_ADMIN_CONSOLE || '') === '1'
    return `${window.location.origin}${isAdminConsole ? '/admin' : '/ai-ecosystem'}`
  })

  const readyStatus = computed(() => {
    if (clientMode.value && !cursorEnabled.value) return 'off'
    if (remoteControlEnabled.value && cursorConnected.value) return 'ready'
    if (remoteControlEnabled.value || cursorEnabled.value) return 'partial'
    return 'off'
  })

  const aiOpenActive = computed(() => cursorEnabled.value || (!clientMode.value && remoteControlEnabled.value))

  const featureIntro = [
    { icon: '◎', title: '虚拟光标', desc: 'AI 看见页面，帮你点击和输入' },
    { icon: '⚡', title: '业务调用', desc: '查订单、发消息、调接口' },
    { icon: '🔗', title: '开放接入', desc: 'Cursor / Claude / VS Code 等均可配置' },
  ]

  const flowSteps = ['保持页面打开', '让 AI 连上', '有操作时自动出现']

  const anyClientInstalled = computed(() => installedClientIds.value.length > 0)

  const flowDone = computed(() => [
    aiOpenActive.value,
    anyClientInstalled.value || hasConnectConfig.value || hasActiveClientKey.value,
    readyStatus.value === 'ready',
  ])

  const statusText = computed(() => {
    if (readyStatus.value === 'ready') return '已就绪 · 默认静默待命，Agent 操作时才出现光标'
    if (clientMode.value && cursorEnabled.value && !remoteControlEnabled.value) return '本页已待命 · 服务端智控尚未开启'
    if (readyStatus.value === 'partial') return '正在连接 · 请保持本页打开'
    return '已关闭 · 可在「更多设置」中重新开启'
  })

  const primaryBtnLabel = computed(() => {
    if (setupRunning.value) return '开启中…'
    if (clientMode.value) return aiOpenActive.value ? '关闭本页待命' : '开启本页待命'
    if (remoteControlEnabled.value) return '关闭智控'
    return '一键开启'
  })

  const friendlyTools = computed(() =>
    manifestTools.value.map((t) => ({
      name: t.name,
      label: TOOL_LABELS[t.name]?.label || t.name,
      desc: TOOL_LABELS[t.name]?.desc || t.description,
    }))
  )

  const aiClients = computed<AiMcpClientInstall[]>(() =>
    buildAiopenClientInstalls(reachableOrigin.value, activeKey.value)
  )

  const selectedClient = computed(() => aiClients.value.find((c) => c.id === selectedClientId.value) || aiClients.value[0])

  const selectedClientConfigSnippet = computed(() => selectedClient.value?.mcpJson || '')

  return {
    TOOL_LABELS,
    wechatOpen,
    routes,
    remoteControlEnabled,
    keys,
    usage,
    usageRecent,
    newKey,
    accessResult,
    panelError,
    panelAvailable,
    clientMode,
    hasActiveClientKey,
    keyRunning,
    manifestTools,
    setupRunning,
    shutdownRunning,
    seedRunning,
    loopRunning,
    loopResultText,
    installBundle,
    mcpHealthy,
    mcpHealthText,
    installedClientIds,
    selectedClientId,
    stdioScriptPath,
    openclawBase,
    openclawMessage,
    openclawSending,
    openclawResult,
    apiOrigin,
    backendOrigin,
    reachableOrigin,
    consoleUrl,
    activeKey,
    hasConnectConfig,
    readyStatus,
    aiOpenActive,
    featureIntro,
    flowSteps,
    anyClientInstalled,
    flowDone,
    statusText,
    primaryBtnLabel,
    friendlyTools,
    aiClients,
    selectedClient,
    selectedClientConfigSnippet,
  }
}

export type AiOpenPanelState = ReturnType<typeof useAiOpenPanelState>
