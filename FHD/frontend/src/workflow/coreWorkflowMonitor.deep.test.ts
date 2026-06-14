import { describe, it, expect } from 'vitest'
import { STAR_REFRESH_STORAGE_KEY } from './coreWorkflowPrefs'
import {
  appendCoreWorkflowSummaryParts,
  buildCoreWorkflowMonitorLine,
  buildCoreWorkflowStepsForEmployee,
  computeCoreWorkflowCurrentHint,
  computeCoreWorkflowProgressState,
  computeCoreWorkflowStageLine,
  computeWorkflowProgressFromSteps,
  mergeCorePayloadFromExisting,
} from './coreWorkflowMonitor'

function withStarRefresh(on: boolean, fn: () => void) {
  const prev = localStorage.getItem(STAR_REFRESH_STORAGE_KEY)
  if (on) localStorage.setItem(STAR_REFRESH_STORAGE_KEY, '1')
  else localStorage.removeItem(STAR_REFRESH_STORAGE_KEY)
  try {
    fn()
  } finally {
    if (prev == null) localStorage.removeItem(STAR_REFRESH_STORAGE_KEY)
    else localStorage.setItem(STAR_REFRESH_STORAGE_KEY, prev)
  }
}

describe('coreWorkflowMonitor', () => {
  it('computeWorkflowProgressFromSteps returns zero state for empty', () => {
    const result = computeWorkflowProgressFromSteps([])
    expect(result.pct).toBe(0)
    expect(result.label).toContain('0')
  })

  it('computeWorkflowProgressFromSteps counts done steps', () => {
    const steps = [
      { status: 'done' as const, label: 'a' },
      { status: 'active' as const, label: 'b' },
      { status: 'pending' as const, label: 'c' },
    ]
    const result = computeWorkflowProgressFromSteps(steps)
    expect(result.pct).toBeGreaterThan(0)
    expect(result.pct).toBeLessThanOrEqual(100)
  })

  it('buildCoreWorkflowStepsForEmployee returns array', () => {
    const steps = buildCoreWorkflowStepsForEmployee('wechat_msg', {})
    expect(Array.isArray(steps)).toBe(true)
  })

  it('mergeCorePayloadFromExisting returns object for core employee', () => {
    const merged = mergeCorePayloadFromExisting('wechat_msg', undefined, {})
    expect(typeof merged).toBe('object')
  })

  it('appendCoreWorkflowSummaryParts appends wechat parts', () => {
    const parts: string[] = []
    appendCoreWorkflowSummaryParts('wechat_msg', parts, {
      lastWechat: { at: Date.now(), line: 'hello' },
    })
    expect(parts.length).toBe(1)
  })

  it('buildCoreWorkflowMonitorLine formats wechat line', () => {
    const line = buildCoreWorkflowMonitorLine('wechat_msg')
    expect(typeof line).toBe('string')
    expect(line.length).toBeGreaterThan(0)
  })

  it('computeCoreWorkflowStageLine returns stage text', () => {
    const line = computeCoreWorkflowStageLine('wechat_msg', { stage: 'run' })
    expect(typeof line).toBe('string')
  })

  it('computeCoreWorkflowCurrentHint returns hint', () => {
    const hint = computeCoreWorkflowCurrentHint('label_print', {})
    expect(typeof hint).toBe('string')
  })

  it('computeCoreWorkflowProgressState returns state object', () => {
    const state = computeCoreWorkflowProgressState('shipment_mgmt', [])
    expect(state).toBeDefined()
  })

  it('buildCoreWorkflowMonitorLine covers all core employees', () => {
    for (const empId of ['wechat_msg', 'label_print', 'shipment_mgmt', 'receipt_confirm'] as const) {
      const line = buildCoreWorkflowMonitorLine(empId, { lastPolledAt: Date.now(), pollIntervalMs: 60000 })
      expect(typeof line).toBe('string')
      expect(line.length).toBeGreaterThan(0)
    }
  })

  it('computeCoreWorkflowCurrentHint covers core employees with ctx', () => {
    const ctx = {
      lastWechat: { at: Date.now(), line: 'msg' },
      lastLabelPrint: { at: Date.now(), line: 'print' },
      lastShipmentAudit: { at: Date.now(), line: 'audit' },
      lastReceiptFeedback: { at: Date.now(), line: 'rcpt' },
    }
    for (const empId of ['wechat_msg', 'label_print', 'shipment_mgmt', 'receipt_confirm'] as const) {
      expect(typeof computeCoreWorkflowCurrentHint(empId, ctx)).toBe('string')
    }
  })

  it('computeCoreWorkflowStageLine covers core employees', () => {
    const ctx = { lastWechat: { at: 1, line: 'x' } }
    for (const empId of ['wechat_msg', 'label_print', 'shipment_mgmt', 'receipt_confirm'] as const) {
      expect(typeof computeCoreWorkflowStageLine(empId, ctx)).toBe('string')
    }
  })

  it('buildCoreWorkflowMonitorLine shows poll failure when pollOk is false', () => {
    withStarRefresh(true, () => {
      const line = buildCoreWorkflowMonitorLine('wechat_msg', {
        lastPolledAt: Date.now(),
        pollIntervalMs: 60000,
        pollOk: false,
        starredContactCount: 2,
      })
      expect(line).toContain('拉取失败')
    })
  })

  it('buildCoreWorkflowMonitorLine pauses when star refresh off', () => {
    withStarRefresh(false, () => {
      const line = buildCoreWorkflowMonitorLine('wechat_msg')
      expect(line).toContain('监控已暂停')
    })
  })

  it('buildCoreWorkflowMonitorLine truncates long label print line', () => {
    withStarRefresh(true, () => {
      const long = 'x'.repeat(120)
      const line = buildCoreWorkflowMonitorLine('label_print', undefined, {
        lastLabelPrint: { at: Date.now(), line: long },
      })
      expect(line).toContain('…')
    })
  })

  it('computeCoreWorkflowCurrentHint truncates long shipment detail', () => {
    const long = 'd'.repeat(250)
    const hint = computeCoreWorkflowCurrentHint('shipment_mgmt', {
      lastShipmentAudit: { at: Date.now(), line: 'audit', detail: long },
    })
    expect(hint.endsWith('…')).toBe(true)
  })

  it('appendCoreWorkflowSummaryParts covers all employee ctx branches', () => {
    const now = Date.now()
    const cases: Array<[Parameters<typeof appendCoreWorkflowSummaryParts>[0], string]> = [
      ['wechat_msg', '最近处理'],
      ['label_print', '最近标签'],
      ['shipment_mgmt', '最近打印后审计'],
      ['receipt_confirm', '最近客户反馈'],
    ]
    for (const [empId, needle] of cases) {
      const parts: string[] = []
      appendCoreWorkflowSummaryParts(empId, parts, {
        lastWechat: { at: now, line: 'w' },
        lastLabelPrint: { at: now, line: 'l' },
        lastShipmentAudit: { at: now, line: 's' },
        lastReceiptFeedback: { at: now, line: 'r' },
      })
      expect(parts.some((p) => p.includes(needle))).toBe(true)
    }
  })

  it('mergeCorePayloadFromExisting merges from existing payload', () => {
    const merged = mergeCorePayloadFromExisting('wechat_msg', undefined, {
      lastWechat: { at: 1, line: 'from-payload' },
    })
    expect(merged.lastWechat?.line).toBe('from-payload')
  })

  it('mergeCorePayloadFromExisting ignores non-core employee', () => {
    expect(mergeCorePayloadFromExisting('unknown_emp', {}, { foo: 1 })).toEqual({})
  })

  it('computeCoreWorkflowProgressState started when signal present', () => {
    withStarRefresh(true, () => {
      const steps = buildCoreWorkflowStepsForEmployee('wechat_msg', {
        lastWechat: { at: Date.now(), line: 'hi' },
      })
      const state = computeCoreWorkflowProgressState('wechat_msg', steps, {
        lastWechat: { at: Date.now(), line: 'hi' },
      })
      expect(state.workflowProgressStarted).toBe(true)
      expect(state.progressPct).toBeGreaterThan(0)
    })
  })

  it('computeCoreWorkflowProgressState receipt_confirm idle without refresh', () => {
    withStarRefresh(false, () => {
      const state = computeCoreWorkflowProgressState('receipt_confirm', [], {})
      expect(state.workflowProgressStarted).toBe(false)
      expect(state.progressLabel).toContain('星标自动刷新')
    })
  })

  it('computeCoreWorkflowProgressState receipt_confirm idle with refresh on', () => {
    withStarRefresh(true, () => {
      const state = computeCoreWorkflowProgressState('receipt_confirm', [], {})
      expect(state.progressLabel).toContain('尚未收到')
    })
  })

  it('computeCoreWorkflowProgressState label_print idle without star refresh', () => {
    withStarRefresh(false, () => {
      const state = computeCoreWorkflowProgressState('label_print', [], {})
      expect(state.workflowProgressStarted).toBe(false)
      expect(state.progressLabel).toContain('星标自动刷新')
    })
  })

  it('computeCoreWorkflowProgressState label_print idle with star refresh on', () => {
    withStarRefresh(true, () => {
      const state = computeCoreWorkflowProgressState('label_print', [], {})
      expect(state.progressLabel).toContain('等待微信侧标签')
    })
  })

  it('computeCoreWorkflowProgressState shipment_mgmt idle awaits audit', () => {
    const state = computeCoreWorkflowProgressState('shipment_mgmt', [], {})
    expect(state.workflowProgressStarted).toBe(false)
    expect(state.progressLabel).toContain('打印后审计')
  })

  it('computeCoreWorkflowProgressState wechat_msg idle without star refresh', () => {
    withStarRefresh(false, () => {
      const state = computeCoreWorkflowProgressState('wechat_msg', [], {})
      expect(state.workflowProgressStarted).toBe(false)
      expect(state.progressLabel).toContain('星标自动刷新')
    })
  })

  it('computeCoreWorkflowProgressState wechat_msg idle with star refresh on', () => {
    withStarRefresh(true, () => {
      const state = computeCoreWorkflowProgressState('wechat_msg', [], {})
      expect(state.progressLabel).toContain('等待新消息')
    })
  })

  it('computeCoreWorkflowProgressState label_print started with signal', () => {
    withStarRefresh(true, () => {
      const steps = buildCoreWorkflowStepsForEmployee('label_print', {
        lastLabelPrint: { at: Date.now(), line: 'print ok' },
      })
      const state = computeCoreWorkflowProgressState('label_print', steps, {
        lastLabelPrint: { at: Date.now(), line: 'print ok' },
      })
      expect(state.workflowProgressStarted).toBe(true)
      expect(state.progressPct).toBeGreaterThan(0)
    })
  })

  it('mergeCorePayloadFromExisting prefers opts over existing payload', () => {
    const merged = mergeCorePayloadFromExisting(
      'wechat_msg',
      { lastWechat: { at: 2, line: 'from-opts' } },
      { lastWechat: { at: 1, line: 'from-payload' } },
    )
    expect(merged.lastWechat?.line).toBe('from-opts')
  })

  it('appendCoreWorkflowSummaryParts ignores non-core employee', () => {
    const parts: string[] = []
    appendCoreWorkflowSummaryParts('not-core', parts, {
      lastWechat: { at: 1, line: 'x' },
    })
    expect(parts).toEqual([])
  })

  it('computeWorkflowProgressFromSteps all done has no active suffix', () => {
    const steps = [
      { status: 'done' as const, label: 'a' },
      { status: 'done' as const, label: 'b' },
    ]
    const result = computeWorkflowProgressFromSteps(steps)
    expect(result.pct).toBe(100)
    expect(result.label).not.toContain('进行中')
  })

  it('buildCoreWorkflowStepsForEmployee wechat_msg with pro intent label', () => {
    localStorage.setItem('xcagi_pro_intent_experience', '1')
    try {
      const steps = buildCoreWorkflowStepsForEmployee('wechat_msg', {
        lastWechat: { at: Date.now(), line: 'hi' },
      })
      const step4 = steps.find((s) => s.id === 'wx4')
      expect(step4?.label).toContain('intent/test')
      expect(step4?.status).toBe('done')
    } finally {
      localStorage.removeItem('xcagi_pro_intent_experience')
    }
  })

  it('buildCoreWorkflowStepsForEmployee shipment_mgmt with audit active', () => {
    const steps = buildCoreWorkflowStepsForEmployee('shipment_mgmt', {
      lastShipmentAudit: { at: Date.now(), line: '审计完成' },
    })
    expect(steps.some((s) => s.status === 'active')).toBe(true)
  })

  it('computeCoreWorkflowCurrentHint wechat with monitor polled', () => {
    withStarRefresh(true, () => {
      const hint = computeCoreWorkflowCurrentHint('wechat_msg', {}, {
        lastPolledAt: Date.now(),
      })
      expect(hint).toContain('轮询')
    })
  })

  it('computeCoreWorkflowCurrentHint receipt_confirm requires star refresh', () => {
    withStarRefresh(false, () => {
      const hint = computeCoreWorkflowCurrentHint('receipt_confirm', {})
      expect(hint).toContain('星标聊天自动刷新')
    })
  })

  it('computeCoreWorkflowCurrentHint receipt_confirm with feedback detail', () => {
    withStarRefresh(true, () => {
      const long = 'x'.repeat(250)
      const hint = computeCoreWorkflowCurrentHint('receipt_confirm', {
        lastReceiptFeedback: { at: Date.now(), line: '签收', detail: long },
      })
      expect(hint.endsWith('…')).toBe(true)
    })
  })

  it('computeCoreWorkflowCurrentHint shipment_mgmt idle explains audit flow', () => {
    const hint = computeCoreWorkflowCurrentHint('shipment_mgmt', {})
    expect(hint).toContain('开始打印')
  })
})
