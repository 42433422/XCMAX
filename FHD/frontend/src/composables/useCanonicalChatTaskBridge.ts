import type { Ref } from 'vue'
import agentRunsApi, { type AgentRun, type AgentRunResponse } from '../api/agentRuns'
import { asRecord } from '@/utils/typeGuards'
import { runHasUncertainReceipt } from '@/utils/agentRunExecution'
import { taskStatusLabel } from '@/utils/taskWorkspacePresentation'
import type { ShipmentTask } from './useShipmentTask'

type DynamicShipmentTask = ShipmentTask & Record<string, unknown>

interface CanonicalChatTaskBridgeOptions {
  sessionId: Ref<string>
  createTaskId: (prefix: string) => string
  refreshTasks: () => Promise<void>
}

export function useCanonicalChatTaskBridge(options: CanonicalChatTaskBridgeOptions) {
  const staging = new Map<string, Promise<AgentRunResponse>>()
  function canonicalTaskRequest(
    task: ShipmentTask,
    paramsOverride?: Record<string, unknown>,
  ): { toolId: string; action: string; params: Record<string, unknown> } | null {
    const payload = asRecord(task.payload)
    const requestedToolId = String(payload.tool_id || asRecord(payload.params).tool_id || task.tool_id || '').trim()
    const rawAction = String(payload.action || asRecord(payload.params).action || '').trim()
    const toolId = requestedToolId === 'shipment_generate' ? 'shipment_orders' : requestedToolId
    const action = requestedToolId === 'shipment_generate' ? 'generate' : rawAction
    if (!toolId || !action) return null
    const params = { ...(paramsOverride || asRecord(payload.params)) }
    const orderNumber = String(task.customOrderNumber || task.order_number || '').trim()
    if (toolId === 'shipment_orders' && action === 'generate' && orderNumber) {
      params.order_number = orderNumber
    }
    return { toolId, action, params }
  }

  function hasCanonicalTarget(task: ShipmentTask): boolean {
    return Boolean(String((task as DynamicShipmentTask).agentRunId || '').trim() || canonicalTaskRequest(task))
  }

  async function stageCanonicalTask(task: ShipmentTask, paramsOverride?: Record<string, unknown>): Promise<AgentRunResponse | null> {
    const mutableTask = task as DynamicShipmentTask
    const runId = String(mutableTask.agentRunId || '')
    if (runId) {
      const receipt = await agentRunsApi.getRun(runId)
      if (receipt.data?.run_id !== runId) throw new Error('原任务回执不匹配，请核对任务状态')
      if (mutableTask.agentRestageRequested && receipt.data.status === 'cancelled' && !runHasUncertainReceipt(receipt.data)) {
        delete mutableTask.agentRunId
        delete mutableTask.agentTaskId
        delete mutableTask.agentCancelRequested
        delete mutableTask.agentRestageRequested
        return stageCanonicalTask(task, paramsOverride)
      }
      return receipt
    }
    const request = canonicalTaskRequest(task, paramsOverride)
    if (!request) return null
    const taskId = String(mutableTask.agentTaskId || options.createTaskId('chat_task'))
    mutableTask.agentTaskId = taskId
    if (staging.has(taskId)) return staging.get(taskId)!
    const pending = agentRunsApi.createTask({
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
    }).then(async (created) => {
      if (!created.data) throw new Error('任务持久化失败')
      if (mutableTask.agentTaskId === taskId) mutableTask.agentRunId = created.data.run_id
      if (mutableTask.agentCancelRequested) {
        await agentRunsApi.cancelRun(created.data.run_id)
        return agentRunsApi.getRun(created.data.run_id)
      }
      return created
    }).finally(async () => {
      staging.delete(taskId)
      await options.refreshTasks()
    })
    staging.set(taskId, pending)
    return pending
  }

  async function executeCanonicalTask(task: ShipmentTask, paramsOverride?: Record<string, unknown>): Promise<Response | null> {
    const request = canonicalTaskRequest(task, paramsOverride)
    const created = await stageCanonicalTask(task, paramsOverride)
    if (!created) return null
    if (!created?.data) throw new Error('任务持久化失败')
    let run: AgentRun = created.data
    if (request && run.status === 'waiting_user' && !(task as DynamicShipmentTask).agentCancelRequested && created.approval?.grant) {
      const grant = created.approval?.grant
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
    const status = runHasUncertainReceipt(run) ? 'unknown' : run.status
    const completed = status === 'completed' && taskOutput.success !== false
    const terminal = ['completed', 'failed', 'cancelled', 'interrupted', 'rejected'].includes(status)
    const responseBody = {
      ...taskOutput,
      success: completed,
      run_id: run.run_id,
      task_id: String((task as DynamicShipmentTask).agentTaskId || ''),
      execution_state: status,
      requires_reconciliation: status === 'unknown',
      message: status === 'unknown' ? '结果待核对，请查看原任务回执，勿重复提交。'
        : terminal ? taskOutput.message || run.error || (completed ? '任务执行成功' : '任务执行未完成')
          : `任务${taskStatusLabel(status)}，请在任务工作区查看原任务进度。`,
    }
    await options.refreshTasks()
    return {
      ok: completed,
      status: completed ? 200 : terminal || status === 'unknown' ? 409 : 202,
      json: async () => responseBody,
    } as Response
  }

  function invalidateStagedTask(task: ShipmentTask, nextOrderNumber: string): void {
    const mutableTask = task as DynamicShipmentTask
    const runId = String(mutableTask.agentRunId || '')
    if (nextOrderNumber === task.customOrderNumber || (!runId && !staging.has(String(mutableTask.agentTaskId || '')))) return
    mutableTask.agentCancelRequested = true
    mutableTask.agentRestageRequested = true
    if (!runId) return
    void agentRunsApi.cancelRun(runId).then((receipt) => {
      if (receipt.data?.run_id !== runId || receipt.data.status !== 'cancelled' || runHasUncertainReceipt(receipt.data)) return
      if (mutableTask.agentRunId !== runId) return
      delete mutableTask.agentRunId
      delete mutableTask.agentTaskId
      delete mutableTask.agentCancelRequested
      delete mutableTask.agentRestageRequested
    }).catch(() => { /* Retain the original identity until cancellation is confirmed. */ })
      .finally(() => options.refreshTasks())
  }

  function cancelCanonicalTask(task: ShipmentTask | null): void {
    const mutableTask = task as DynamicShipmentTask | null
    if (!mutableTask) return
    mutableTask.agentCancelRequested = true
    const runId = String(mutableTask.agentRunId || '')
    if (runId) void agentRunsApi.cancelRun(runId).catch(() => { /* Read the original task to reconcile. */ })
      .finally(() => options.refreshTasks())
  }

  return { hasCanonicalTarget, stageCanonicalTask, executeCanonicalTask, invalidateStagedTask, cancelCanonicalTask }
}
