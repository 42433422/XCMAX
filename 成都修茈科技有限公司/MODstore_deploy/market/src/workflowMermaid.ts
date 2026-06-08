type WorkflowNodeLike = {
  id?: unknown
  node_type?: unknown
  name?: unknown
}

type WorkflowEdgeLike = {
  id?: unknown
  source_node_id?: unknown
  target_node_id?: unknown
  condition?: unknown
}

function asNodeList(nodes: unknown): WorkflowNodeLike[] {
  return Array.isArray(nodes) ? nodes.filter((n): n is WorkflowNodeLike => !!n && typeof n === 'object' && !Array.isArray(n)) : []
}

function asEdgeList(edges: unknown): WorkflowEdgeLike[] {
  return Array.isArray(edges) ? edges.filter((e): e is WorkflowEdgeLike => !!e && typeof e === 'object' && !Array.isArray(e)) : []
}

function mermaidSafeId(nodeId: unknown): string {
  const s = String(nodeId == null ? 'x' : nodeId).replace(/[^a-zA-Z0-9_]/g, '_')
  return `N_${s}`
}

function mermaidEscapeLabel(text: unknown): string {
  return String(text ?? '')
    .replace(/\\/g, '\\\\')
    .replace(/"/g, "'")
    .replace(/[[\]]/g, ' ')
    .replace(/\n/g, ' ')
    .trim()
    .slice(0, 80)
}

export function computeGraphSummary(nodes: unknown, edges: unknown): { counts: Record<string, number>; warnings: string[]; unreachableIds: unknown[] } {
  const ns = asNodeList(nodes)
  const es = asEdgeList(edges)
  const counts: Record<string, number> = {}
  for (const n of ns) {
    const t = typeof n.node_type === 'string' ? n.node_type : 'unknown'
    counts[t] = (counts[t] || 0) + 1
  }
  const nodeIds = new Set(ns.map((n) => n.id))
  const warnings: string[] = []
  const adj = new Map<unknown, unknown[]>()
  for (const id of nodeIds) adj.set(id, [])

  for (const e of es) {
    const s = e.source_node_id
    const t = e.target_node_id
    if (!nodeIds.has(s) || !nodeIds.has(t)) {
      warnings.push(`边 #${e.id ?? '?'} 引用缺失节点（源 ${s} → 目标 ${t}）`)
      continue
    }
    adj.get(s)?.push(t)
  }

  const starts = ns.filter((n) => n.node_type === 'start')
  if (starts.length === 0) warnings.push('缺少开始节点')
  else if (starts.length > 1) warnings.push(`开始节点数量: ${starts.length}（期望 1）`)

  for (const n of ns) {
    if (n.node_type === 'end') continue
    const outs = adj.get(n.id) || []
    if (outs.length === 0) warnings.push(`节点「${n.name || n.id}」无出边（非结束节点）`)
  }

  let unreachableIds: unknown[] = []
  if (starts.length === 1) {
    const startId = starts[0].id
    const seen = new Set<unknown>()
    const q = [startId]
    while (q.length) {
      const u = q.pop()
      if (seen.has(u)) continue
      seen.add(u)
      for (const v of adj.get(u) || []) {
        if (!seen.has(v)) q.push(v)
      }
    }
    unreachableIds = ns.map((n) => n.id).filter((id) => !seen.has(id))
    if (unreachableIds.length) warnings.push(`自开始节点不可达: ${unreachableIds.length} 个节点`)
  }

  return { counts, warnings, unreachableIds }
}

export function buildMermaidFlowchart(nodes: unknown, edges: unknown): string {
  const ns = asNodeList(nodes)
  const es = asEdgeList(edges)
  if (!ns.length) return 'flowchart TD\n  empty["（无节点）"]\n'

  const lines = ['flowchart TD']
  for (const n of ns) {
    const mid = mermaidSafeId(n.id)
    const typ = mermaidEscapeLabel(n.node_type || '?')
    const nm = mermaidEscapeLabel(n.name || String(n.id))
    lines.push(`  ${mid}["${nm} (${typ})"]`)
  }
  for (const e of es) {
    const a = mermaidSafeId(e.source_node_id)
    const b = mermaidSafeId(e.target_node_id)
    const cond = (e.condition && String(e.condition).trim()) || ''
    if (cond) {
      const c = mermaidEscapeLabel(cond).slice(0, 48)
      lines.push(`  ${a} -->|"${c}"| ${b}`)
    } else {
      lines.push(`  ${a} --> ${b}`)
    }
  }
  return lines.join('\n')
}
