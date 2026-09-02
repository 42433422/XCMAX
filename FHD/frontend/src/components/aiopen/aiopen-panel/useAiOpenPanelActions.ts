import { safeJsonRequest } from '@/utils/safeJsonRequest'
import { AIOPEN_MCP_SERVER_NAME, markAiopenClientInstalled, readAiopenInstalledClients, unmarkAiopenClientInstalled } from '@/utils/aiopenMcpInstall'
import type { AiMcpClientInstall } from '@/utils/aiopenMcpInstall'
import type { AiOpenPanelState, AiopenInstallPayload, AiopenManifestPayload, AiopenPanelPayload, AiopenWhitelistRoute } from './useAiOpenPanelState'

type PanelResult = AiopenPanelPayload & { success?: boolean }
type ManifestProbePayload = { success?: boolean; server?: string; tool_count?: number }
type KeyResultPayload = { success?: boolean; key?: string }
type SeedResultPayload = { routes?: AiopenWhitelistRoute[]; enabled_count?: number }
type LoopVerifyPayload = { closed_loop?: boolean; success?: boolean; hint?: string }

type CheckEvent = Event | { target?: { checked?: boolean } | null }

const eventChecked = (event: CheckEvent | undefined): boolean =>
  Boolean((event?.target as { checked?: boolean } | null)?.checked)

// AIOpenPanel 的加载 / 拷贝 / 口令 / 开关 / 白名单逻辑（与拆分前逐字一致）
export function useAiOpenPanelActions(state: AiOpenPanelState, options: { setCursorEnabled: (value: boolean) => void }) {
  const {
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
    guideUrl,
    activeKey,
    hasConnectConfig,
    aiAssistantPrompt,
    oneLinerText,
    aiOpenActive,
    aiClients,
    selectedClient,
  } = state
  const { setCursorEnabled } = options

  const refreshInstalledClients = () => {
    installedClientIds.value = readAiopenInstalledClients()
  }

  const loadInstallBundle = async () => {
    const qs = activeKey.value ? `?key=${encodeURIComponent(activeKey.value)}` : ''
    try {
      const result = await safeJsonRequest<AiopenInstallPayload>(`/api/aiopen/install${qs}`)
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
      const manifest = await safeJsonRequest<AiopenManifestPayload>('/api/aiopen/manifest')
      if (manifest.ok && manifest.data?.success && manifest.data?.name === 'AIOPEN') {
        const count = Array.isArray(manifest.data.tools) ? manifest.data.tools.length : 9
        mcpHealthy.value = true
        mcpHealthText.value = `MCP 服务正常 · ${count} 个工具已注册`
        return
      }
      const probe = await safeJsonRequest<ManifestProbePayload>('/api/aiopen/mcp')
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

  const clientActionLabel = (client: Pick<AiMcpClientInstall, 'id' | 'installLabel'>) =>
    installedClientIds.value.includes(client.id) ? '再次点击取消' : client.installLabel

  const resetClientSelection = (client: Pick<AiMcpClientInstall, 'id' | 'name'>) => {
    unmarkAiopenClientInstalled(client.id)
    refreshInstalledClients()
    if (selectedClientId.value === client.id) {
      selectedClientId.value = 'cursor'
    }
    accessResult.value = `${client.name} 已取消 · 可再次点击配置`
  }

  const handleClientClick = async (client: AiMcpClientInstall) => {
    if (!client) return
    if (installedClientIds.value.includes(client.id)) {
      resetClientSelection(client)
      return
    }
    await installForClient(client)
  }

  const installForClient = async (client: AiMcpClientInstall) => {
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

  const copyClientConfig = (clientId: string) => {
    const client = aiClients.value.find((c) => c.id === clientId) || selectedClient.value
    if (client) copyText(client.mcpJson)
  }

  const formatPanelError = (result: { status?: number; message?: string }) => {
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
      const result = await safeJsonRequest<PanelResult>('/api/aiopen/panel')
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
      const mf = await safeJsonRequest<AiopenManifestPayload>('/api/aiopen/manifest')
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

  const copyText = async (text: string) => {
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
    const result = await safeJsonRequest<KeyResultPayload>('/api/aiopen/keys', {
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
    if (aiOpenActive.value) return
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

  const shutdownAiOpen = async () => {
    shutdownRunning.value = true
    accessResult.value = ''
    try {
      remoteControlEnabled.value = false
      setCursorEnabled(false)
      if (panelAvailable.value) {
        await safeJsonRequest('/api/aiopen/control', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: false }),
        })
      }
      accessResult.value = '已关闭开放智控'
    } finally {
      shutdownRunning.value = false
    }
  }

  const handlePrimaryAction = async () => {
    if (aiOpenActive.value) {
      await shutdownAiOpen()
      return
    }
    await quickSetup()
  }

  const toggleWhitelist = async (path: string, event: CheckEvent) => {
    const enabled = eventChecked(event)
    routes.value = routes.value.map((item) => (item.path === path ? { ...item, enabled } : item))
    if (!panelAvailable.value) return
    await safeJsonRequest('/api/aiopen/whitelist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, enabled }),
    })
  }

  const seedFullWhitelist = async () => {
    if (!panelAvailable.value) return
    seedRunning.value = true
    loopResultText.value = ''
    try {
      const result = await safeJsonRequest<SeedResultPayload>('/api/aiopen/whitelist/seed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: true, merge: true }),
      })
      if (result.ok && result.data?.routes) {
        routes.value = Array.isArray(result.data.routes) ? result.data.routes : routes.value
        loopResultText.value = `已开启全业务白名单（${result.data.enabled_count || 0} 条）`
      } else {
        loopResultText.value = result.message || '白名单写入失败'
      }
    } finally {
      seedRunning.value = false
    }
  }

  const verifyCapabilityLoop = async () => {
    if (!panelAvailable.value) return
    loopRunning.value = true
    loopResultText.value = ''
    try {
      const result = await safeJsonRequest<LoopVerifyPayload>('/api/aiopen/loop/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (result.ok && result.data) {
        const ok = Boolean(result.data.closed_loop || result.data.success)
        loopResultText.value = ok
          ? (result.data.hint || '全调用闭环通过')
          : (result.data.hint || result.message || '闭环未通过')
      } else {
        loopResultText.value = result.message || '闭环检测失败'
      }
    } finally {
      loopRunning.value = false
    }
  }

  const toggleWechat = async (event: CheckEvent) => {
    wechatOpen.value = eventChecked(event)
    if (!panelAvailable.value) return
    await safeJsonRequest('/api/ai/qclaw/wechat-gateway', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: wechatOpen.value }),
    })
  }

  const toggleRemoteControl = async (event: CheckEvent) => {
    remoteControlEnabled.value = eventChecked(event)
    if (!panelAvailable.value) return
    await safeJsonRequest('/api/aiopen/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: remoteControlEnabled.value }),
    })
  }

  const toggleScreenSession = (event: CheckEvent) => {
    setCursorEnabled(eventChecked(event))
  }

  return {
    refreshInstalledClients,
    loadInstallBundle,
    probeMcpHealth,
    clientActionLabel,
    resetClientSelection,
    handleClientClick,
    installForClient,
    copyClientConfig,
    formatPanelError,
    loadPanel,
    copyText,
    copyOneLiner,
    copyAiAssistantPrompt,
    copyCursorConfig,
    copyGuideUrl,
    copyGuidePrompt,
    createKey,
    quickSetup,
    shutdownAiOpen,
    handlePrimaryAction,
    toggleWhitelist,
    seedFullWhitelist,
    verifyCapabilityLoop,
    toggleWechat,
    toggleRemoteControl,
    toggleScreenSession,
  }
}

export type AiOpenPanelActions = ReturnType<typeof useAiOpenPanelActions>
