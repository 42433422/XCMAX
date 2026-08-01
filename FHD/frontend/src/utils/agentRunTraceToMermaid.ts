/**
 * 把 AgentRunTraceData 转成 mermaid flowchart 源码字符串。
 *
 * 用于在 AgentRunTrace 组件中渲染计划图（Codex 风格的可视化增强）。
 * 节点形状：
 * - planner  → 圆角矩形 `([文本])`（stadium）
 * - tool      → 子流程图 `[[文本]]`（subroutine）
 * - run       → 圆形 `(((文本)))`（circle，终态）
 *
 * 状态着色（classDef）：
 * - running   蓝
 * - success   绿
 * - failed    红
 * - waiting   琥珀
 * - blocked   灰
 */

import type { AgentRunTraceData, TracePhase } from './agentRunTraceModel'
import { shouldShowAgentRunPlanGraph } from './agentRunTraceModel'

const NODE_SHAPE: Record<TracePhase['kind'], (id: string, label: string) => string> = {
  planner: (id, label) => `${id}([${label}])`,
  tool: (id, label) => `${id}[[${label}]]`,
  run: (id, label) => `${id}(((${label})))`,
}

const STATUS_CLASS: Record<TracePhase['status'], string> = {
  running: 'st-running',
  success: 'st-success',
  failed: 'st-failed',
  waiting: 'st-waiting',
  blocked: 'st-blocked',
  cancelled: 'st-cancelled',
}

function escapeMermaidLabel(text: string): string {
  // mermaid 节点标签里的特殊字符需要处理：括号、引号、管道符
  return text
    .replace(/\\/g, '\\\\')
    .replace(/["]/g, '#quot;')
    .replace(/\[/g, '(')
    .replace(/\]/g, ')')
    .replace(/\n/g, ' ')
    .trim()
    .slice(0, 40)
}

function nodeId(idx: number): string {
  return `p${idx}`
}

function nodeLabel(phase: TracePhase): string {
  if (phase.kind === 'tool') {
    return escapeMermaidLabel(phase.tool_id || phase.action || phase.title || 'tool')
  }
  return escapeMermaidLabel(phase.title || phase.kind)
}

/**
 * 生成 mermaid flowchart 源码。空 trace 返回空字符串。
 */
export function traceToMermaid(trace: AgentRunTraceData | null | undefined): string {
  if (!trace || !trace.phases.length) return ''
  // 单工具 / trivial：不生成图（避免「执行计划图太丑」抢视线）
  if (!shouldShowAgentRunPlanGraph(trace)) return ''

  const lines: string[] = ['flowchart TD']

  // 节点定义 + class
  for (let i = 0; i < trace.phases.length; i += 1) {
    const phase = trace.phases[i]
    const id = nodeId(i)
    const label = nodeLabel(phase)
    const shape = NODE_SHAPE[phase.kind](id, label)
    lines.push(`  ${shape}`)
    lines.push(`  class ${id} ${STATUS_CLASS[phase.status]}`)
  }

  // 边：按顺序连接相邻 phase
  for (let i = 0; i < trace.phases.length - 1; i += 1) {
    const cur = trace.phases[i]
    const next = trace.phases[i + 1]
    const fromId = nodeId(i)
    const toId = nodeId(i + 1)
    // 失败的边加标签
    if (cur.status === 'failed' || next.status === 'failed') {
      lines.push(`  ${fromId} -->|失败| ${toId}`)
    } else if (cur.status === 'waiting' || next.status === 'waiting') {
      lines.push(`  ${fromId} -->|等待| ${toId}`)
    } else {
      lines.push(`  ${fromId} --> ${toId}`)
    }
  }

  // classDef（同时定义 light/dark，mermaid 主题会选其一）
  lines.push('  classDef st-running fill:#dbeafe,stroke:#3b82f6,color:#1e40af,stroke-width:2px')
  lines.push('  classDef st-success fill:#d1fae5,stroke:#10b981,color:#065f46,stroke-width:2px')
  lines.push('  classDef st-failed fill:#fee2e2,stroke:#ef4444,color:#991b1b,stroke-width:2px')
  lines.push('  classDef st-waiting fill:#fef3c7,stroke:#f59e0b,color:#92400e,stroke-width:2px')
  lines.push('  classDef st-blocked fill:#f3f4f6,stroke:#9ca3af,color:#4b5563,stroke-width:1px')
  lines.push('  classDef st-cancelled fill:#f3f4f6,stroke:#9ca3af,color:#4b5563,stroke-width:1px')

  return lines.join('\n')
}
