import type { Ref } from 'vue'
import agentRunsApi, { type AgentRun, type AgentRunResponse } from '../api/agentRuns'
import { asRecord } from '@/utils/typeGuards'
import type { ShipmentTask } from './useShipmentTask'

type DynamicShipmentTask = ShipmentTask & Record<string, unknown>

interface CanonicalChatTaskBridgeOptions {
  sessionId: Ref<string>
  createTaskId: (prefix: string) => string
  refreshTasks: () => Promise<void>
}

export function useCanonicalChatTaskBridge(options: CanonicalChatTaskBridgeOptions) {
  function canonicalTaskRequest(
    task: ShipmentTask,
    paramsOverride?: Record<string, unknown>,
  ): { toolId: string; action: string; params: Record<string, unknown> } | null {
    const payload = asRecord(task.payload)
    const requestedToolId = String(
      payload.tool_id || asRecord(payload.params).tool_id || task.tool_id || '',
    ).trim()
    const rawAction = String(payload.action || asRecord(payload.params).action || '').trim()
    const toolId = requestedToolId === 'shipment_generate'
      ? 'shipment_orders'
      : requestedToolId === 'import_excel_to_database'
        ? 'excel_import'
        : requestedToolId
    const action = requestedToolId === 'shipment_generate' ? 'generate' : rawAction
    if (!toolId || !action) return null
    const params = { ...(paramsOverride || asRecord(payload.params)) }
    const orderNumber = String(task.customOrderNumber || task.order_number || '').trim()
    if (toolId === 'shipment_orders' && action === 'generate' && orderNumber) {
      params.order_number = orderNumber
    }
    return { toolId, action, params }
  }

  async function stageCanonicalTask(
    task: ShipmentTask,
    paramsOverride?: Record<string, unknown>,
  ): Promise<AgentRunResponse | null> {
    const request = canonicalTaskRequest(task, paramsOverride)
    if (!request) return null
    const mutableTask = task as DynamicShipmentTask
    const taskId = String(mutableTask.agentTaskId || options.createTaskId('chat_task'))
    mutableTask.agentTaskId = taskId
    const created = await agentRunsApi.createTask({
      task_id: taskId,
      title: String(task.title || '智能任务'),
      message: String(task.description || task.title || '智能任务'),
      tool_id: request.toolId,
      action: request.action,
      params: request.params,
      runtime_context: {
        conversation_id: String(options.sessionId.value || ''),
        source: 'chat_task_card',
      },
    })
    if (!created.data) throw new Error('任务持久化失败')
    mutableTask.agentRunId = created.data.run_id
    if (mutableTask.agentCancelRequested) await agentRunsApi.cancelRun(created.data.run_id)
    await options.refreshTasks()
    return created
  }

  async function executeCanonicalTask(
    task: ShipmentTask,
    paramsOverride?: Record<string, unknown>,
  ): Promise<Response | null> {
    if (!canonicalTaskRequest(task, paramsOverride)) return null
    delete (task as DynamicShipmentTask).agentCancelRequested
    const created = await stageCanonicalTask(task, paramsOverride)
    if (!created?.data) throw new Error('任务持久化失败')
    let run: AgentRun = created.data
    if (run.status === 'waiting_user') {
      const grant = created.approval?.grant
      if (!grant) throw new Error('任务审批凭证不可用')
      const approved = await agentRunsApi.continueRun(run.run_id, {
        approval_grant: grant,
        runtime_context: { source: 'chat_task_card_approval' },
      })
      if (!approved.data) throw new Error('审批结果不可用')
      run = approved.data
    }
    const nodeOutputs = asRecord(run.final_output).node_outputs
    const outputRows = Object.values(asRecord(nodeOutputs))
    const taskOutput = asRecord(outputRows[outputRows.length - 1])
    const responseBody = Object.keys(taskOutput).length
      ? taskOutput
      : {
          success: run.status === 'completed',
          message: run.status === 'completed' ? '任务执行成功' : (run.error || '任务执行失败'),
        }
    await options.refreshTasks()
    return {
      ok: run.status === 'completed' && responseBody.success !== false,
      status: run.status === 'completed' ? 200 : 409,
      json: async () => responseBody,
    } as Response
  }

  function invalidateStagedTask(task: ShipmentTask, nextOrderNumber: string): void {
    const mutableTask = task as DynamicShipmentTask
    const runId = String(mutableTask.agentRunId || '')
    if (!runId || nextOrderNumber === task.customOrderNumber) return
    void agentRunsApi.cancelRun(runId).finally(() => options.refreshTasks())
    delete mutableTask.agentRunId
    delete mutableTask.agentTaskId
  }

  function cancelCanonicalTask(task: ShipmentTask | null): void {
    const mutableTask = task as DynamicShipmentTask | null
    if (!mutableTask) return
    mutableTask.agentCancelRequested = true
    const runId = String(mutableTask.agentRunId || '')
    if (runId) void agentRunsApi.cancelRun(runId).finally(() => options.refreshTasks())
  }

  return { stageCanonicalTask, executeCanonicalTask, invalidateStagedTask, cancelCanonicalTask }
}
