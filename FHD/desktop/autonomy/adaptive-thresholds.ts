/**
 * 自适应阈值加载器——把 CRASH_THRESHOLD=3 这类硬常量降为带 floor/ceiling 的软约束。
 * 桌面端优先读 XCAGI_ADAPTIVE_THRESHOLDS_JSON 环境变量（由主进程注入），否则用内置默认。
 */

export interface AdaptiveThreshold {
  name: string
  value: number
  floor: number
  ceiling: number
  unit?: string
  source?: string
}

const DEFAULTS: Record<string, AdaptiveThreshold> = {
  crash_threshold: {
    name: 'crash_threshold',
    value: 3,
    floor: 2,
    ceiling: 5,
    unit: 'count_per_window',
    source: 'default',
  },
  crash_window_ms: {
    name: 'crash_window_ms',
    value: 5 * 60 * 1000,
    floor: 60_000,
    ceiling: 30 * 60 * 1000,
    unit: 'ms',
    source: 'default',
  },
  disk_clean_threshold: {
    name: 'disk_clean_threshold',
    value: 70,
    floor: 60,
    ceiling: 90,
    unit: 'percent',
    source: 'default',
  },
  restart_count_cap: {
    name: 'restart_count_cap',
    value: 3,
    floor: 2,
    ceiling: 6,
    unit: 'count',
    source: 'default',
  },
}

function clamp(t: AdaptiveThreshold): AdaptiveThreshold {
  const value = Math.min(t.ceiling, Math.max(t.floor, t.value))
  return { ...t, value }
}

export function loadAdaptiveThresholds(
  overrideJson?: string | null,
): Record<string, AdaptiveThreshold> {
  const out: Record<string, AdaptiveThreshold> = { ...DEFAULTS }
  const raw = (overrideJson ?? process.env.XCAGI_ADAPTIVE_THRESHOLDS_JSON ?? '').trim()
  if (!raw) return out
  try {
    const parsed = JSON.parse(raw) as { thresholds?: Record<string, Partial<AdaptiveThreshold>> }
    const items = parsed.thresholds ?? (parsed as Record<string, Partial<AdaptiveThreshold>>)
    for (const [name, base] of Object.entries(DEFAULTS)) {
      const item = items[name]
      if (!item || typeof item !== 'object') continue
      out[name] = clamp({
        name,
        value: Number(item.value ?? base.value),
        floor: Number(item.floor ?? base.floor),
        ceiling: Number(item.ceiling ?? base.ceiling),
        unit: String(item.unit ?? base.unit ?? ''),
        source: String(item.source ?? 'env'),
      })
    }
  } catch {
    // fail-open to defaults
  }
  return out
}

export function getThreshold(name: string, overrideJson?: string | null): AdaptiveThreshold {
  const all = loadAdaptiveThresholds(overrideJson)
  return all[name] ?? {
    name,
    value: 0,
    floor: 0,
    ceiling: 0,
    source: 'missing',
  }
}
