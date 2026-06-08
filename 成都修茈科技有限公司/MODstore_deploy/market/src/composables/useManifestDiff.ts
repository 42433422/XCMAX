/**
 * Compares the current workbench manifest against a baseline snapshot stored in
 * sessionStorage to surface what changed during a re-edit session.
 *
 * Scope: flat key-path diffs for the fields users typically care about:
 *   identity, cognition.agent, collaboration.workflow, commerce, metadata.suggested_pricing
 *
 * Full recursive deep-diff is intentionally avoided to keep the output readable.
 */

import { computed } from 'vue'
import { useWorkbenchStore } from '../stores/workbench'

export interface DiffEntry {
  path: string
  label: string
  before: unknown
  after: unknown
}

// Human-readable labels for well-known paths
const PATH_LABELS: Record<string, string> = {
  'identity.name': '员工名称',
  'identity.id': '员工 ID',
  'identity.version': '版本号',
  'identity.description': '描述',
  'cognition.agent.system_prompt': 'System Prompt',
  'cognition.agent.role.name': '角色名',
  'cognition.agent.role.persona': '人设',
  'cognition.agent.role.tone': '语气风格',
  'cognition.agent.model.provider': '模型提供商',
  'cognition.agent.model.model_name': '模型名称',
  'cognition.agent.model.temperature': '温度',
  'collaboration.workflow.workflow_id': '工作流 ID',
  'commerce.price': '定价（元）',
  'commerce.tier': '定价档位',
  'commerce.period': '计费周期',
}

// Paths to always compare (ordered)
const WATCHED_PATHS = Object.keys(PATH_LABELS)

function getByPath(obj: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce<unknown>((cur, key) => {
    if (cur == null || typeof cur !== 'object') return undefined
    return (cur as Record<string, unknown>)[key]
  }, obj)
}

function serialize(val: unknown): string {
  if (val === undefined || val === null) return ''
  if (typeof val === 'string') return val
  return JSON.stringify(val)
}

export function useManifestDiff() {
  const store = useWorkbenchStore()

  const baselineManifest = computed<Record<string, unknown> | null>(() => {
    const id = store.target.id
    if (!id) return null
    try {
      const raw = sessionStorage.getItem(`workbench_baseline_manifest_${id}`)
      if (!raw) return null
      return JSON.parse(raw) as Record<string, unknown>
    } catch {
      return null
    }
  })

  const diffs = computed<DiffEntry[]>(() => {
    const baseline = baselineManifest.value
    if (!baseline) return []
    const current = store.target.manifest
    const entries: DiffEntry[] = []
    for (const path of WATCHED_PATHS) {
      const before = getByPath(baseline, path)
      const after = getByPath(current, path)
      if (serialize(before) !== serialize(after)) {
        entries.push({
          path,
          label: PATH_LABELS[path] ?? path,
          before,
          after,
        })
      }
    }
    return entries
  })

  const diffCount = computed(() => diffs.value.length)
  const hasDiff = computed(() => diffCount.value > 0)
  const hasBaseline = computed(() => baselineManifest.value !== null)

  return { diffs, diffCount, hasDiff, hasBaseline }
}
