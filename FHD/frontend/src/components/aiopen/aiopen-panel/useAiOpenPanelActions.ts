import { watch } from 'vue'
import { safeJsonRequest } from '@/utils/safeJsonRequest'
import { captureAuthSession, getAuthSessionEpoch } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { AIOPEN_MCP_SERVER_NAME, buildAiopenOneLiner, markAiopenClientInstalled, readAiopenInstalledClients, unmarkAiopenClientInstalled } from '@/utils/aiopenMcpInstall'
import type { AiMcpClientInstall } from '@/utils/aiopenMcpInstall'
import type { AiOpenPanelState, AiopenInstallPayload, AiopenManifestPayload, AiopenPanelPayload, AiopenWhitelistRoute } from './useAiOpenPanelState'

type PanelResult = AiopenPanelPayload & { success?: boolean }
type ManifestProbePayload = { success?: boolean; server?: string; tool_count?: number }
type KeyResultPayload = { success?: boolean; key?: string; expires_at?: number }
type SeedResultPayload = { routes?: AiopenWhitelistRoute[]; enabled_count?: number }
type LoopVerifyPayload = { closed_loop?: boolean; success?: boolean; hint?: string }

type CheckEvent = Event | { target?: { checked?: boolean } | null }

const eventChecked = (event: CheckEvent | undefined): boolean =>
  Boolean((event?.target as { checked?: boolean } | null)?.checked)

export function useAiOpenPanelActions(state: AiOpenPanelState, options: { setCursorEnabled: (value: boolean) => void }) {
  const {
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
    reachableOrigin,
    consoleUrl,
    activeKey,
    hasConnectConfig,
    aiOpenActive,
    aiClients,
    selectedClient,
  } = state
  const { setCursorEnabled } = options
  let copyCredential: { key: string; expiresAt: number } | undefined

  const refreshInstalledClients = () => {
    installedClientIds.value = readAiopenInstalledClients()
  }

  const loadInstallBundle = async () => {
    try {
      const result = await safeJsonRequest<AiopenInstallPayload>('/api/aiopen/install')
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
    if (!client || !await copyClientConfig(client.id)) return
    selectedClientId.value = client.id
    markAiopenClientInstalled(client.id)
    refreshInstalledClients()
    accessResult.value = `${client.name} 配置已复制 · 粘贴到 ${client.configPath}`
  }

  const copyClientConfig = async (clientId: string) => {
    if (!panelAvailable.value || keyRunning.value) return false
    const isCurrent = captureAuthSession()
    if (!activeKey.value) {
      if (clientMode.value && hasActiveClientKey.value) {
        accessResult.value = '当前口令无法再次显示。需要新配置时，请先点「重新生成口令」。'
        return false
      }
      if (!await createKey() || !isCurrent()) return false
    }
    const client = aiClients.value.find((c) => c.id === clientId) || selectedClient.value
    return client ? copyText(client.mcpJson) : false
  }

  const formatPanelError = (result: { status?: number; message?: string }) => {
    if (result.status === 401) return '请登录 XCAGI 后刷新状态'
    if (result.status === 403) return result.message || '当前账号无法使用 AIOPEN'
    if (result.status === 404) return '后端未就绪（路由未生效，请重启服务）'
    if (result.status === 502 || result.status === 500) {
      return '后端未启动或暂不可用，请稍后刷新状态'
    }
    if (result.message?.includes('未返回JSON')) {
      return '后端未启动或暂不可用，请稍后刷新状态'
    }
    return result.message || '无法连接后端'
  }

  const loadPanel = async () => {
    const isCurrent = captureAuthSession()
    panelError.value = ''
    accessResult.value = ''
    try {
      const admin = await safeJsonRequest<PanelResult>('/api/aiopen/panel')
      const result = admin.status === 403 ? await safeJsonRequest<PanelResult>('/api/aiopen/client') : admin
      if (!isCurrent()) return
      if (result.ok && result.data?.success && (admin.status !== 403 || result.data.client_mode === true)) {
        clientMode.value = result.data.client_mode === true
        hasActiveClientKey.value = clientMode.value && result.data.has_active_key === true
        if (clientMode.value && !hasActiveClientKey.value) {
          copyCredential = undefined
          newKey.value = ''
        }
        panelAvailable.value = true
        wechatOpen.value = !clientMode.value && Boolean(result.data.wechat_open)
        routes.value = !clientMode.value && Array.isArray(result.data.routes) ? result.data.routes : []
        openclawBase.value = String(result.data.openclaw_base || 'http://localhost:28789')
        remoteControlEnabled.value = Boolean(result.data.remote_control_enabled)
        keys.value = Array.isArray(result.data.keys) ? result.data.keys : []
      } else {
        panelAvailable.value = false
        copyCredential = undefined
        newKey.value = ''
        panelError.value = formatPanelError(result)
        routes.value = []
      }
    } catch {
      if (!isCurrent()) return
      panelAvailable.value = false
      copyCredential = undefined
      newKey.value = ''
      panelError.value = '无法连接后端，请稍后刷新状态'
      routes.value = []
    }
    usage.value = null
    usageRecent.value = []
    if (panelAvailable.value && !clientMode.value) try {
      const usageResult = await safeJsonRequest<{
        success?: boolean
        summary?: Record<string, unknown>
        recent?: Array<Record<string, unknown>>
      }>('/api/aiopen/usage?days=7&recent=10')
      if (isCurrent() && usageResult.ok && usageResult.data?.success) {
        usage.value = usageResult.data.summary || null
        usageRecent.value = Array.isArray(usageResult.data.recent) ? usageResult.data.recent : []
      }
    } catch {
      /* 计量接口失败不影响面板主流程 */
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
    if (isCurrent()) {
      await loadInstallBundle()
      await probeMcpHealth()
    }
  }

  watch([getAuthSessionEpoch, productReadAccountEpoch], () => {
    copyCredential = undefined
    newKey.value = ''
    keys.value = []
    hasActiveClientKey.value = false
    panelAvailable.value = false
    void loadPanel()
  }, { flush: 'sync' })

  const copyText = async (text: string) => {
    try {
      if (window.xcagiDesktop?.clipboardWriteText) {
        if (!(await window.xcagiDesktop.clipboardWriteText(text)).ok) throw new Error('copy failed')
      } else {
        await navigator.clipboard.writeText(text)
      }
      accessResult.value = '已复制'
      return true
    } catch {
      accessResult.value = '写入剪贴板失败，请再点一次「复制一句话」'
      return false
    }
  }

  const copyOneLiner = async () => {
    if (!panelAvailable.value || keyRunning.value) return
    const isCurrent = captureAuthSession()
    keyRunning.value = true
    try {
      if (!copyCredential || copyCredential.expiresAt <= Date.now() / 1000) {
        const result = await safeJsonRequest<KeyResultPayload>('/api/aiopen/client/key?keep_existing=true', { method: 'POST' })
        if (!isCurrent()) return
        const key = result.data?.key?.trim()
        const expiresAt = result.data?.expires_at
        if (!result.ok || !result.data?.success || !key || !expiresAt) {
          accessResult.value = result.message || '未取得连接口令，请刷新状态后重试'
          return
        }
        copyCredential = { key, expiresAt }
        hasActiveClientKey.value = true
      }
      const text = buildAiopenOneLiner(reachableOrigin.value, consoleUrl.value, copyCredential.key)
      if (await copyText(text) && isCurrent()) {
        accessResult.value = '一句话已复制 · 粘贴给本机 AI 助手即可接入'
      }
    } catch {
      if (isCurrent()) accessResult.value = '生成连接口令失败，请刷新状态后重试'
    } finally {
      keyRunning.value = false
    }
  }

  const createKey = async () => {
    if (!panelAvailable.value) {
      accessResult.value = panelError.value || '登录并刷新状态后可获取口令'
      return false
    }
    if (keyRunning.value) return false
    const isCurrent = captureAuthSession()
    const client = clientMode.value
    keyRunning.value = true
    try {
      const result = await safeJsonRequest<KeyResultPayload>(client ? '/api/aiopen/client/key' : '/api/aiopen/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(client ? {} : { label: '面板' }),
      })
      if (!isCurrent()) return false
      const key = result.data?.key?.trim()
      if (result.ok && result.data?.success && key) {
        newKey.value = key
        if (client) {
          copyCredential = undefined
          hasActiveClientKey.value = true
        }
        accessResult.value = '口令已生成，可以复制所选客户端的配置'
        return true
      }
      accessResult.value = result.message || '未取得连接口令'
    } catch {
      if (isCurrent()) accessResult.value = '生成口令失败，请刷新状态'
    } finally {
      keyRunning.value = false
    }
    return false
  }

  const revokeClientKey = async () => {
    if (!panelAvailable.value || keyRunning.value) return
    const isCurrent = captureAuthSession()
    keyRunning.value = true
    try {
      const result = await safeJsonRequest<KeyResultPayload>('/api/aiopen/client/key', { method: 'DELETE' })
      if (!isCurrent()) return
      if (result.ok && result.data?.success) {
        copyCredential = undefined
        if (clientMode.value) newKey.value = ''
        hasActiveClientKey.value = false
        accessResult.value = '本账号的连接口令已撤销'
      } else {
        accessResult.value = result.message || '撤销口令失败'
      }
    } catch {
      if (isCurrent()) accessResult.value = '撤销口令失败，请刷新状态'
    } finally {
      keyRunning.value = false
    }
  }

  const quickSetup = async () => {
    if (aiOpenActive.value) return
    setupRunning.value = true
    accessResult.value = ''
    try {
      if (!panelAvailable.value || (!clientMode.value && !await setRemoteControl(true))) return
      setCursorEnabled(true)
      const ready = clientMode.value || hasConnectConfig.value || await createKey()
      if (ready) accessResult.value = clientMode.value ? '本页已开启待命' : '已开启智控，可选择 AI 软件配置 MCP'
    } finally {
      setupRunning.value = false
    }
  }

  const shutdownAiOpen = async () => {
    shutdownRunning.value = true
    accessResult.value = ''
    try {
      if (!panelAvailable.value || (!clientMode.value && !await setRemoteControl(false))) return
      setCursorEnabled(false)
      accessResult.value = clientMode.value ? '本页已关闭待命' : '已关闭开放智控'
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
    if (!panelAvailable.value || clientMode.value) return
    const enabled = eventChecked(event)
    routes.value = routes.value.map((item) => (item.path === path ? { ...item, enabled } : item))
    await safeJsonRequest('/api/aiopen/whitelist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, enabled }),
    })
  }

  const seedFullWhitelist = async () => {
    if (!panelAvailable.value || clientMode.value) return
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
    if (!panelAvailable.value || clientMode.value) return
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
    if (!panelAvailable.value || clientMode.value) return
    wechatOpen.value = eventChecked(event)
    await safeJsonRequest('/api/ai/qclaw/wechat-gateway', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: wechatOpen.value }),
    })
  }

  const setRemoteControl = async (enabled: boolean) => {
    if (!panelAvailable.value || clientMode.value) return false
    const isCurrent = captureAuthSession()
    try {
      const result = await safeJsonRequest<KeyResultPayload>('/api/aiopen/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      })
      if (!isCurrent()) return false
      if (result.ok && result.data?.success !== false) {
        remoteControlEnabled.value = enabled
        return true
      }
      accessResult.value = result.message || '更新智控开关失败'
    } catch {
      if (isCurrent()) accessResult.value = '更新智控开关失败'
    }
    return false
  }

  const toggleRemoteControl = async (event: CheckEvent) => {
    if (!await setRemoteControl(eventChecked(event)) && event.target instanceof HTMLInputElement) {
      event.target.checked = remoteControlEnabled.value
    }
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
    formatPanelError,
    loadPanel,
    copyOneLiner,
    createKey,
    revokeClientKey,
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
