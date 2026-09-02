import { computed, ref } from 'vue'
import type { Ref } from 'vue'
import { getApiBase } from '@/utils/apiBase'
import {
  buildAiAssistantSetupPrompt,
  buildAiopenClientInstalls,
  buildAiopenOneLiner,
  resolveAiopenBackendBase,
} from '@/utils/aiopenMcpInstall'
import type { AiMcpClientInstall, AiMcpClientId } from '@/utils/aiopenMcpInstall'

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

/**
 * AIOpenPanel 的全部响应式状态与纯展示逻辑（与拆分前逐项对应）。
 * 行为 composable 共享同一组 ref，保证与拆分前同一实例。
 */
export function useAiOpenPanelState(options: { cursorEnabled: Ref<boolean>; cursorConnected: Ref<boolean> }) {
  const { cursorEnabled, cursorConnected } = options

  const TOOL_LABELS: Record<string, { label: string; desc: string }> = {
    api_catalog: { label: '查看接口', desc: '列出可调用的业务接口' },
    api_call: { label: '调用接口', desc: '代你请求订单、产品等业务数据' },
    chat: { label: '对话', desc: '和 XCAGI AI 助手聊天' },
    capability_loop: { label: '闭环自检', desc: '一键验证 catalog→API→对话→光标通道' },
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
  const newKey = ref('')
  const accessResult = ref('')
  const panelError = ref('')
  const panelAvailable = ref(true)
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
      clientId: selectedClientId.value as AiMcpClientId,
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

  const aiOpenActive = computed(() => remoteControlEnabled.value || cursorEnabled.value)

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
    buildAiopenClientInstalls(backendOrigin.value, activeKey.value, {
      stdioScriptPath: stdioScriptPath.value || undefined,
    })
  )

  const selectedClient = computed(() => aiClients.value.find((c) => c.id === selectedClientId.value) || aiClients.value[0])

  const selectedClientConfigSnippet = computed(() => selectedClient.value?.mcpJson || '')

  return {
    TOOL_LABELS,
    wechatOpen,
    routes,
    remoteControlEnabled,
    keys,
    newKey,
    accessResult,
    panelError,
    panelAvailable,
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
    oneLinerCopied,
    openclawBase,
    openclawMessage,
    openclawSending,
    openclawResult,
    apiOrigin,
    backendOrigin,
    mcpUrl,
    guideUrl,
    activeKey,
    hasConnectConfig,
    aiAssistantPrompt,
    oneLinerText,
    oneLinerPreview,
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
