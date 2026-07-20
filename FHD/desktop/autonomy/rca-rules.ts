/**
 * RCA 规则映射：signal kind → root_cause
 *
 * 三端共用枚举（与 FHD/scripts/observability/rca_rules.py 保持同源）。
 * 新增 kind 必须同时更新此处与 Python 端。
 */

import type { Diagnosis, Signal } from './types.js'

/** 9 个核心 kind → root_cause 映射 */
export const RCA_MAP: Record<string, string> = {
  backend_exit: 'backend_crash',
  disk_full: 'disk_pressure',
  config_fingerprint_changed: 'config_drift',
  port_in_use: 'port_conflict',
  LLM_RUNTIME_UNAVAILABLE: 'llm_runtime_down',
  NEURO_BUS_CIRCUIT_OPEN: 'neurobus_circuit_open',
  NEURO_BUS_DLQ_FULL: 'neurobus_dlq_saturated',
  NEURO_BUS_RATE_LIMIT: 'neurobus_rate_limited',
  ota_install_failed: 'ota_install_corrupted',
}

/** 默认诊断（无匹配 kind 时） */
export const DEFAULT_ROOT_CAUSE = 'unknown'

/**
 * 诊断纯函数：根据信号列表生成诊断。
 * 取最近一条信号作为主因，证据取最近 5 条信号的 detail。
 */
export function diagnoseRootCause(signals: Signal[]): Diagnosis {
  if (signals.length === 0) {
    return {
      root_cause: DEFAULT_ROOT_CAUSE,
      confidence: 0,
      detail: '无信号输入',
      evidence: [],
    }
  }
  // 按时间倒序，取最新信号作为主因
  const sorted = [...signals].sort((a, b) => b.ts - a.ts)
  const latest = sorted[0]
  const root_cause = RCA_MAP[latest.kind] ?? DEFAULT_ROOT_CAUSE
  const evidence = sorted.slice(0, 5).map(s => `[${s.kind}] ${s.detail}`)
  return {
    root_cause,
    confidence: root_cause === DEFAULT_ROOT_CAUSE ? 0.3 : 0.8,
    detail: `最近信号: ${latest.kind} - ${latest.detail}`,
    evidence,
  }
}
