import type { ChatApprovalCard } from '@/types/chat-ui'
import type { AgentRunTraceData, TracePlannerPhase, TraceToolPhase } from '@/utils/agentRunTraceModel'

function inferredTool(card: ChatApprovalCard): { toolId: string; action: string } {
  const haystack = [card.reason, card.intent, ...(card.blocking_nodes || [])].filter(Boolean).join(' ')
  const dotted = haystack.match(/\b([a-z][a-z0-9_-]*)\.([a-z][a-z0-9_-]*)\b/i)
  if (dotted) return { toolId: dotted[1], action: dotted[2] }
  const intent = String(card.intent || '')
    .trim()
    .toLowerCase()
  if (intent.startsWith('business_db_')) return { toolId: 'business_db', action: intent.replace(/^business_db_/, '') || 'write' }
  if (intent.includes('excel') && intent.includes('import')) return { toolId: 'excel', action: 'import' }
  return { toolId: 'workflow', action: 'execute' }
}

/**
 * Legacy workflow confirmations do not always expose an AgentRun id yet, but
 * they already carry a structured approval card. Project that payload into the
 * same Business Harness trace model so the UI never falls back to planner prose.
 */
export function buildApprovalCardTrace(card: ChatApprovalCard | null | undefined): AgentRunTraceData | null {
  if (!card || card.status !== 'pending') return null
  const fallback = inferredTool(card)
  const approvalNodes = Array.isArray(card.approval_nodes) ? card.approval_nodes : []
  const blockingNodes = Array.isArray(card.blocking_nodes) ? card.blocking_nodes : []
  const nodeCount = Math.max(approvalNodes.length, blockingNodes.length, 1)
  const phases: Array<TracePlannerPhase | TraceToolPhase> = [
    {
      kind: 'planner',
      status: 'success',
      started_event_id: `${card.plan_id || 'approval'}:planner`,
      title: '执行计划已生成',
      step_count: Math.max(card.todo?.length || 0, nodeCount),
    },
  ]

  for (let index = 0; index < nodeCount; index += 1) {
    const structured = approvalNodes[index] || {}
    const nodeId = String(structured.node_id || blockingNodes[index] || `approval_step_${index + 1}`).trim()
    const toolId = String(structured.tool_id || fallback.toolId).trim()
    const action = String(structured.action || fallback.action).trim()
    phases.push({
      kind: 'tool',
      status: 'waiting',
      started_event_id: `${card.plan_id || card.run_id || 'approval'}:${nodeId}`,
      title: toolId ? `工具调用 · ${toolId}` : '工具调用',
      subtitle: action || undefined,
      node_id: nodeId,
      tool_id: toolId,
      action,
      observations: card.todo || [],
      waiting_approval: true,
      retries: 0,
      repair_history: [],
    })
  }

  return {
    run_id: String(card.agent_run_id || card.run_id || card.plan_id || 'approval_pending'),
    intent: String(card.intent || '').trim(),
    status: 'waiting',
    phases,
    terminal: false,
  }
}
