import bundledAutomationPolicyRaw from '../../../config/six_line_employee_map.json'

/** Parse six_line_employee_map.json into admin-console cards (ticket #53). */

export type AutomationPolicyStep = {
  id: string
  name: string
  primary: string[]
  support: string[]
}

export type AutomationPolicyLine = {
  key: string
  label: string
  steps: AutomationPolicyStep[]
}

export type AutomationPolicyDoc = {
  version: string
  description: string
  lines: AutomationPolicyLine[]
  coverageNote: string
  linesInScope: number
}

type RawStep = {
  name?: unknown
  primary?: unknown
  support?: unknown
}

function asStringList(v: unknown): string[] {
  if (!Array.isArray(v)) return []
  return v.map((x) => String(x || '').trim()).filter(Boolean)
}

export function parseAutomationPolicyDoc(raw: unknown): AutomationPolicyDoc {
  const root = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {}
  const linesRaw = root.lines && typeof root.lines === 'object' ? (root.lines as Record<string, unknown>) : {}
  const coverage =
    root.coverage && typeof root.coverage === 'object' ? (root.coverage as Record<string, unknown>) : {}

  const lines: AutomationPolicyLine[] = Object.entries(linesRaw).map(([key, value]) => {
    const line = value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
    const stepsRaw = line.steps && typeof line.steps === 'object' ? (line.steps as Record<string, RawStep>) : {}
    const steps: AutomationPolicyStep[] = Object.entries(stepsRaw).map(([id, step]) => ({
      id,
      name: String(step?.name || id),
      primary: asStringList(step?.primary),
      support: asStringList(step?.support),
    }))
    return {
      key,
      label: String(line.label || key),
      steps,
    }
  })

  return {
    version: String(root.version || ''),
    description: String(root.description || ''),
    lines,
    coverageNote: String(coverage.note || ''),
    linesInScope: Number(coverage.lines_in_scope || lines.length) || lines.length,
  }
}

/** Same-origin dashboard static copy; falls back to FHD config mount if present. */
export function automationPolicyMapUrls(): string[] {
  const origin =
    typeof window !== 'undefined' && window.location?.origin ? window.location.origin : ''
  const paths = [
    '/xcmax-dashboard/FHD/config/six_line_employee_map.json',
    '/xcmax-dashboard/six_line_employee_map.json?v=20260603u',
  ]
  return paths.map((p) => (origin ? `${origin}${p}` : p))
}

/** Bundled SSOT fallback when /xcmax-dashboard static map is unavailable. */
export function bundledAutomationPolicyDoc(): AutomationPolicyDoc {
  return parseAutomationPolicyDoc(bundledAutomationPolicyRaw)
}
