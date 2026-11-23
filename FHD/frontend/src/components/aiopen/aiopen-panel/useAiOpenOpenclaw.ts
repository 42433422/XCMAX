import { ref } from 'vue'
import { safeJsonRequest } from '@/utils/safeJsonRequest'
import type { AiOpenPanelState } from './useAiOpenPanelState'

// OpenClaw messages use the same approved capability task as other tools.
export function useAiOpenOpenclaw(state: AiOpenPanelState) {
  const { panelAvailable, clientMode, openclawBase, openclawMessage, openclawSending, openclawResult } = state

  const openclawWsUrl = ref('ws://localhost:28789/ws')
  const openclawWsAuthMode = ref('token')
  const openclawGatewayToken = ref('')
  const wsConnected = ref(false)
  const wsConnecting = ref(false)
  const wsStatusText = ref('')
  let wsClient: WebSocket | null = null
  const openclawTaskId = ref('')
  let pendingRequest: { body: string; requestId: string } | null = null

  const saveOpenclawBase = async () => {
    if (!panelAvailable.value || clientMode.value) return
    const result = await safeJsonRequest('/api/aiopen/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_url: openclawBase.value }),
    })
    openclawResult.value = result.ok ? '已保存' : result.message
  }

  const sendToOpenclaw = async () => {
    if (!panelAvailable.value || clientMode.value) return
    const params = { message: openclawMessage.value.trim(), gateway_url: openclawBase.value.trim().replace(/\/+$/, '') }
    const body = JSON.stringify(params)
    if (!pendingRequest || pendingRequest.body !== body) {
      pendingRequest = { body, requestId: crypto.randomUUID() }
      openclawTaskId.value = ''
    } else if (openclawTaskId.value) {
      openclawResult.value = '请查看原任务进度并处理审批，勿重复发送。'
      return
    }
    openclawSending.value = true
    openclawResult.value = ''
    try {
      const result = await safeJsonRequest('/api/tools/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_id: 'openclaw', action: 'chat', params, request_id: pendingRequest.requestId }),
      })
      const d = result?.data as { success?: boolean; execution_state?: string; pending_approval?: boolean; task_id?: string; message?: string } | null
      openclawTaskId.value = d?.task_id || ''
      openclawResult.value = d?.message || result.message || (d?.pending_approval
        ? '等待审批，请查看原任务。'
        : result.ok && d?.success && d.execution_state === 'completed' ? '业务结果已核验' : '结果待核对，请查看原任务，勿重复发送。')
    } catch (err) {
      openclawResult.value = String((err as Error)?.message || err)
    } finally {
      openclawSending.value = false
    }
  }

  const connectOpenclawWs = () => {
    if (!panelAvailable.value || clientMode.value || wsConnected.value || wsConnecting.value) return
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
    openclawTaskId,
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
