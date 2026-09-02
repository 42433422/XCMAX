import { ref } from 'vue'
import { safeJsonRequest } from '@/utils/safeJsonRequest'
import type { AiOpenPanelState } from './useAiOpenPanelState'

// AIOpenPanel 的 OpenClaw HTTP / WebSocket 通道逻辑（与拆分前逐字一致）
export function useAiOpenOpenclaw(state: AiOpenPanelState) {
  const { panelAvailable, openclawBase, openclawMessage, openclawSending, openclawResult } = state

  const openclawWsUrl = ref('ws://localhost:28789/ws')
  const openclawWsAuthMode = ref('token')
  const openclawGatewayToken = ref('')
  const wsConnected = ref(false)
  const wsConnecting = ref(false)
  const wsStatusText = ref('')
  let wsClient: WebSocket | null = null

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
      const d = result?.data as { success?: boolean } | null
      openclawResult.value = result.ok && d?.success ? '发送成功' : (result.message || '失败')
    } catch (err) {
      openclawResult.value = String((err as Error)?.message || err)
    } finally {
      openclawSending.value = false
    }
  }

  const connectOpenclawWs = () => {
    if (wsConnected.value || wsConnecting.value) return
    wsConnecting.value = true
    try {
      wsClient = new WebSocket(String(openclawWsUrl.value || '').trim())
      wsClient.onopen = () => { wsConnecting.value = false; wsStatusText.value = 'WS 已连接' }
      wsClient.onmessage = (event: MessageEvent) => {
        let msg: { event?: string; type?: string; payload?: { type?: string } } | null = null
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

  // 卸载时关闭 WS（对应拆分前 onBeforeUnmount 中的 wsClient 清理）
  const closeOpenclawWs = () => {
    wsClient?.close()
    wsClient = null
  }

  return {
    openclawWsUrl,
    openclawWsAuthMode,
    openclawGatewayToken,
    wsConnected,
    wsConnecting,
    wsStatusText,
    saveOpenclawBase,
    sendToOpenclaw,
    connectOpenclawWs,
    closeOpenclawWs,
  }
}

export type AiOpenOpenclaw = ReturnType<typeof useAiOpenOpenclaw>
