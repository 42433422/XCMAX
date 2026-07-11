import { describe, expect, it } from 'vitest'

import {
  managementAcceptanceGate,
  type ManagementWorkItem,
} from './managementWork'

function delivered(overrides: Partial<ManagementWorkItem> = {}): ManagementWorkItem {
  return {
    task_id: 'mwi_1',
    title: '验证上线任务',
    description: '',
    owner_employee_id: 'delivery-receipt-officer',
    status: 'delivered',
    priority: 'P0',
    risk_level: 'medium',
    progress: 100,
    attempt_count: 2,
    max_attempts: 3,
    fact_evidence: [
      {
        evidence_id: 'evidence_2',
        task_id: 'mwi_1',
        attempt: 2,
        check_id: 'http_health',
        criterion_ids: ['criterion_1'],
        kind: 'http',
        trust_level: 'independent_observation',
        status: 'pass',
        observed_at: '2026-07-10T00:00:00Z',
        expires_at: '2026-07-12T00:00:00Z',
        payload_sha256: 'a'.repeat(64),
        signature: 'b'.repeat(64),
      },
    ],
    verification_receipts: [
      {
        receipt_id: 'receipt_2',
        task_id: 'mwi_1',
        attempt: 2,
        result_digest: 'result',
        fact_bundle_digest: 'facts',
        fact_required: true,
        fact_outcome: 'pass',
        audit_outcome: 'pass',
        status: 'pass',
        verifier_employee_id: 'delivery-receipt-officer',
      },
    ],
    operations: [
      {
        operation_id: 'operation_2',
        operation_key: 'mwi_1:deploy',
        task_id: 'mwi_1',
        employee_id: 'deploy-release-officer',
        task_revision: 1,
        logical_step: 'deploy',
        attempt: 2,
        kind: 'http',
        target: 'local-runtime',
        request_digest: 'request',
        status: 'succeeded',
        reversible: true,
        compensation_status: 'not_required',
      },
    ],
    ...overrides,
  }
}

describe('managementAcceptanceGate', () => {
  const now = Date.parse('2026-07-11T00:00:00Z')

  it('allows only the current attempt with passing facts and settled operations', () => {
    const gate = managementAcceptanceGate(delivered(), now)
    expect(gate.allowed).toBe(true)
    expect(gate.receipt?.receipt_id).toBe('receipt_2')
    expect(gate.blockers).toEqual([])
  })

  it('does not let a historical PASS receipt approve a retried delivery', () => {
    const item = delivered({
      verification_receipts: [
        {
          receipt_id: 'receipt_1',
          task_id: 'mwi_1',
          attempt: 1,
          result_digest: 'old',
          fact_bundle_digest: 'old',
          fact_required: false,
          fact_outcome: 'pass',
          audit_outcome: 'pass',
          status: 'pass',
        },
      ],
    })
    const gate = managementAcceptanceGate(item, now)
    expect(gate.allowed).toBe(false)
    expect(gate.blockers.join('\n')).toContain('第 2 次执行没有与当前 task_id 匹配的独立验收回执')
  })

  it('blocks expired facts and uncertain side effects', () => {
    const item = delivered({
      fact_evidence: delivered().fact_evidence?.map((fact) => ({
        ...fact,
        expires_at: '2026-07-10T00:00:00Z',
      })),
      operations: delivered().operations?.map((operation) => ({
        ...operation,
        status: 'uncertain',
      })),
    })
    const gate = managementAcceptanceGate(item, now)
    expect(gate.allowed).toBe(false)
    expect(gate.blockers.join('\n')).toContain('已于')
    expect(gate.blockers.join('\n')).toContain('结果尚未收口')
  })

  it.each([
    ['task_id', { task_id: '' }, '缺少 task_id'],
    ['attempt', { attempt: 0 }, '缺少有效 attempt'],
    ['trust_level', { trust_level: '' }, 'independent_observation'],
    ['payload_sha256', { payload_sha256: '' }, '缺少 payload_sha256'],
    ['signature', { signature: '' }, '缺少独立采集签名'],
    ['expires_at', { expires_at: '' }, '缺少 expires_at'],
  ])('blocks current facts with missing %s', (_field, factPatch, expected) => {
    const fact = delivered().fact_evidence?.[0]
    expect(fact).toBeDefined()
    const gate = managementAcceptanceGate(delivered({
      fact_evidence: [{ ...fact!, ...factPatch }],
    }), now)
    expect(gate.allowed).toBe(false)
    expect(gate.blockers.join('\n')).toContain(expected)
  })

  it.each([
    ['task_id', { task_id: '' }, '缺少 task_id'],
    ['unknown status', { status: 'pending' }, '状态缺失或未知'],
    ['missing status', { status: '' }, '状态缺失或未知'],
    ['unknown compensation', { compensation_status: 'mystery' }, '补偿状态缺失或未知'],
    ['missing compensation', { compensation_status: '' }, '补偿状态缺失或未知'],
  ])('blocks malformed operation %s', (_field, operationPatch, expected) => {
    const operation = delivered().operations?.[0]
    expect(operation).toBeDefined()
    const gate = managementAcceptanceGate(delivered({
      operations: [{ ...operation!, ...operationPatch }],
    }), now)
    expect(gate.allowed).toBe(false)
    expect(gate.blockers.join('\n')).toContain(expected)
  })

  it.each([
    ['result_digest', { result_digest: '' }, '缺少 result_digest'],
    ['fact_bundle_digest', { fact_bundle_digest: '' }, '缺少 fact_bundle_digest'],
    ['verifier', { verifier_employee_id: 'other-employee' }, 'delivery-receipt-officer'],
  ])('blocks incomplete current receipt %s', (_field, receiptPatch, expected) => {
    const receipt = delivered().verification_receipts?.[0]
    expect(receipt).toBeDefined()
    const gate = managementAcceptanceGate(delivered({
      verification_receipts: [{ ...receipt!, ...receiptPatch }],
    }), now)
    expect(gate.allowed).toBe(false)
    expect(gate.blockers.join('\n')).toContain(expected)
  })
})
