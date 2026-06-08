/**
 * Manifest ↔ Vue Flow nodes/edges 双向映射。
 *
 * 负责把 employee_config_v2 manifest 转为 Vue Flow 节点/边，
 * 以及把画布上的结构变化（新增/删除节点、改变连线）写回 manifest。
 *
 * 模块映射：
 *   identity      → 身份
 *   prompt        → 提示词 (cognition.agent)
 *   skills        → 技能 (cognition.skills)
 *   workflow_heart → 工作流心脏 (collaboration.workflow)
 *   memory        → 记忆
 *   voice         → 语音 (perception.audio + actions.voice_output)
 *   perception    → 感知 (perception)
 *   actions       → 行动 (actions)
 *   management    → 管理
 *   collaboration → 协作/权限 (collaboration.permissions)
 */

import type { Node, Edge } from '@vue-flow/core'

export type EmployeeModuleKind =
  | 'identity'
  | 'prompt'
  | 'skills'
  | 'workflow_heart'
  | 'memory'
  | 'voice'
  | 'perception'
  | 'actions'
  | 'management'
  | 'collaboration'

export interface ModuleMeta {
  kind: EmployeeModuleKind
  label: string
  icon: string
  accent: string
  required: boolean
  /** JSON path(s) in manifest this module maps to */
  paths: string[]
}

export const MODULE_META: Record<EmployeeModuleKind, ModuleMeta> = {
  identity: {
    kind: 'identity', label: '身份', icon: '🪪', accent: '#6366f1', required: true,
    paths: ['identity'],
  },
  prompt: {
    kind: 'prompt', label: '提示词', icon: '💬', accent: '#8b5cf6', required: false,
    paths: ['cognition.agent'],
  },
  skills: {
    kind: 'skills', label: '技能', icon: '⚡', accent: '#f59e0b', required: false,
    paths: ['cognition.skills'],
  },
  workflow_heart: {
    kind: 'workflow_heart', label: '工作流心脏', icon: '❤️', accent: '#ef4444', required: true,
    paths: ['collaboration.workflow'],
  },
  memory: {
    kind: 'memory', label: '记忆', icon: '🧠', accent: '#10b981', required: false,
    paths: ['memory'],
  },
  voice: {
    kind: 'voice', label: '语音', icon: '🎙️', accent: '#06b6d4', required: false,
    paths: ['perception.audio', 'actions.voice_output'],
  },
  perception: {
    kind: 'perception', label: '感知', icon: '👁️', accent: '#3b82f6', required: false,
    paths: ['perception'],
  },
  actions: {
    kind: 'actions', label: '行动', icon: '🎯', accent: '#ec4899', required: false,
    paths: ['actions'],
  },
  management: {
    kind: 'management', label: '管理', icon: '⚙️', accent: '#64748b', required: false,
    paths: ['management'],
  },
  collaboration: {
    kind: 'collaboration', label: '协作权限', icon: '🤝', accent: '#84cc16', required: false,
    paths: ['collaboration.permissions'],
  },
}

// Modules present by default in a new employee
export const DEFAULT_MODULE_ORDER: EmployeeModuleKind[] = [
  'identity',
  'workflow_heart',
  'prompt',
  'skills',
  'memory',
  'perception',
  'voice',
  'actions',
  'management',
  'collaboration',
]

export interface EmployeeNodeData {
  moduleKind: EmployeeModuleKind
  label: string
  meta: ModuleMeta
  /** Slice of the manifest that this node owns */
  slice: unknown
  enabled: boolean
}

function getNestedPath(obj: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce<unknown>((cur, key) => {
    if (cur == null || typeof cur !== 'object') return undefined
    return (cur as Record<string, unknown>)[key]
  }, obj)
}

function isModulePresent(manifest: Record<string, unknown>, kind: EmployeeModuleKind): boolean {
  const meta = MODULE_META[kind]
  if (meta.required) return true
  return meta.paths.some((p) => getNestedPath(manifest, p) != null)
}

function getModuleSlice(manifest: Record<string, unknown>, kind: EmployeeModuleKind): unknown {
  const meta = MODULE_META[kind]
  if (meta.paths.length === 1) return getNestedPath(manifest, meta.paths[0])
  const result: Record<string, unknown> = {}
  for (const p of meta.paths) {
    result[p] = getNestedPath(manifest, p)
  }
  return result
}

/**
 * Convert a manifest into Vue Flow nodes.
 * Only includes modules that are present in the manifest (or required).
 */
export function manifestToNodes(manifest: Record<string, unknown>): Node[] {
  const nodes: Node[] = []
  let col = 0
  let row = 0
  const perRow = 3
  const W = 260
  const H = 110
  const GAP_X = 40
  const GAP_Y = 40

  for (const kind of DEFAULT_MODULE_ORDER) {
    if (!isModulePresent(manifest, kind)) continue
    const meta = MODULE_META[kind]
    const id = `emp-${kind}`
    const x = col * (W + GAP_X)
    const y = row * (H + GAP_Y)
    nodes.push({
      id,
      type: 'employeeModule',
      position: { x, y },
      data: {
        moduleKind: kind,
        label: meta.label,
        meta,
        slice: getModuleSlice(manifest, kind),
        enabled: true,
      } satisfies EmployeeNodeData,
    })
    col++
    if (col >= perRow) {
      col = 0
      row++
    }
  }
  return nodes
}

/**
 * Generate default directed edges for an employee canvas:
 *   identity → workflow_heart → prompt → skills
 * Other modules are standalone (no wiring required by default).
 */
export function manifestToEdges(nodes: Node[]): Edge[] {
  const nodeIds = new Set(nodes.map((n) => n.id))
  const pairs: [string, string][] = [
    ['emp-identity', 'emp-workflow_heart'],
    ['emp-workflow_heart', 'emp-prompt'],
    ['emp-prompt', 'emp-skills'],
  ]
  return pairs
    .filter(([s, t]) => nodeIds.has(s) && nodeIds.has(t))
    .map(([source, target]) => ({
      id: `e-${source}-${target}`,
      source,
      target,
      animated: true,
      style: { stroke: '#6366f1', strokeWidth: 2 },
    }))
}

/**
 * Apply a canvas edge change back to the manifest.
 * Edges in the employee canvas are informational; actual
 * data flow is declared in the workflow JSON. This is a no-op
 * for now but provides the hook for future edge-to-config writes.
 */
export function applyEdgeToManifest(
  _manifest: Record<string, unknown>,
  _source: string,
  _target: string,
): Record<string, unknown> {
  return _manifest
}

/**
 * Add a module node to an existing manifest.
 */
export function addModuleToManifest(
  manifest: Record<string, unknown>,
  kind: EmployeeModuleKind,
): Record<string, unknown> {
  const next = { ...manifest }
  const meta = MODULE_META[kind]

  if (kind === 'memory') {
    next.memory = next.memory ?? {
      short_term: { context_window: 8000, session_timeout: 1800, keep_history: true },
    }
  } else if (kind === 'perception') {
    next.perception = next.perception ?? { vision: { enabled: false }, document: { enabled: false } }
  } else if (kind === 'voice') {
    const p = (next.perception as Record<string, unknown> | undefined) ?? {}
    next.perception = { ...p, audio: { enabled: true, asr: { enabled: true, languages: ['zh-CN'] } } }
    const a = (next.actions as Record<string, unknown> | undefined) ?? {}
    next.actions = { ...a, voice_output: { enabled: true, tts: { provider: 'aliyun', voice_name: '' } } }
  } else if (kind === 'actions') {
    next.actions = next.actions ?? { text_output: { enabled: true, formats: ['text', 'json'] } }
  } else if (kind === 'management') {
    next.management = next.management ?? {
      error_handling: {
        retry_policy: { max_retries: 3, backoff: 'exponential', initial_delay_ms: 1000 },
        fallback_strategy: 'human_handoff',
      },
    }
  } else if (kind === 'collaboration') {
    const c = (next.collaboration as Record<string, unknown> | undefined) ?? {}
    next.collaboration = { ...c, permissions: { access_level: 'read_write' } }
  }

  // For required modules (identity, workflow_heart) this is a no-op
  void meta
  return next
}

/**
 * Remove a module from a manifest. Required modules cannot be removed.
 */
export function removeModuleFromManifest(
  manifest: Record<string, unknown>,
  kind: EmployeeModuleKind,
): Record<string, unknown> {
  const meta = MODULE_META[kind]
  if (meta.required) return manifest
  const next = { ...manifest }
  if (kind === 'memory') delete next.memory
  if (kind === 'perception') delete next.perception
  if (kind === 'voice') {
    const p = { ...(next.perception as Record<string, unknown> | undefined) }
    delete p.audio
    next.perception = Object.keys(p).length ? p : undefined
    const a = { ...(next.actions as Record<string, unknown> | undefined) }
    delete a.voice_output
    next.actions = Object.keys(a).length ? a : undefined
  }
  if (kind === 'actions') delete next.actions
  if (kind === 'management') delete next.management
  if (kind === 'collaboration') {
    const c = { ...(next.collaboration as Record<string, unknown> | undefined) }
    delete c.permissions
    next.collaboration = c
  }
  return next
}
