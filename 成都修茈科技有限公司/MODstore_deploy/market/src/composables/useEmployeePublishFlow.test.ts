import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useEmployeePublishFlow } from './useEmployeePublishFlow'
import { api } from '../api'
import type { WorkflowSandboxResponse } from '../types/api'

vi.mock('../api', () => ({
  api: {
    auditPackage: vi.fn(),
    workflowSandboxRun: vi.fn(),
  },
}))

function sandboxStub(ok: boolean, phase: string): WorkflowSandboxResponse {
  return {
    ok,
    validate_only: phase === 'validate',
    errors: [],
    warnings: [],
    steps: [],
    output: {},
    phase,
  }
}

function createFlow(overrides: Record<string, any> = {}) {
  return useEmployeePublishFlow({
    form: ref({ industry: '', price: 0 }),
    selectedFile: ref(new File(['zip'], 'employee.zip', { type: 'application/zip' })),
    resolvedWorkflowId: ref(12),
    linkedModId: ref('mod-1'),
    listingHints: ref({ industryCoerced: '制造业', priceFromManifest: 88 }),
    employeeConfigV2: ref({ identity: { id: 'agent-1' } }),
    ...overrides,
  })
}

describe('useEmployeePublishFlow', () => {
  it('runs validate and execution sandbox before opening the audit gate', async () => {
    vi.mocked(api.workflowSandboxRun)
      .mockResolvedValueOnce(sandboxStub(true, 'validate'))
      .mockResolvedValueOnce(sandboxStub(true, 'execute'))
    const flow = createFlow()

    await flow.runEmployeeWorkflowSandbox()

    expect(api.workflowSandboxRun).toHaveBeenCalledTimes(2)
    expect(flow.wfSandboxOk.value).toBe(true)
    expect(flow.sandboxGateOk.value).toBe(true)
  })

  it('adds artifact and linked mod metadata to audits', async () => {
    vi.mocked(api.auditPackage).mockResolvedValue({ summary: { pass: true } })
    const flow = createFlow({ resolvedWorkflowId: ref(0) })
    flow.dockerLocalAck.value = true

    await flow.runFiveDimAuditClick('employee_pack')

    expect(api.auditPackage).toHaveBeenCalledWith(expect.any(File), {
      employee_config_v2: { identity: { id: 'agent-1' } },
      artifact: 'employee_pack',
      probe_mod_id: 'mod-1',
    })
    expect(flow.auditReport.value?.summary?.pass).toBe(true)
  })

  it('applies listing defaults when entering listing step', () => {
    const form = ref({ industry: '', price: 0 })
    const flow = createFlow({ form, resolvedWorkflowId: ref(0) })
    flow.dockerLocalAck.value = true
    flow.auditReport.value = { summary: { pass: true } }

    flow.goListingStep()

    expect(flow.publishWizardStep.value).toBe('listing')
    expect(form.value).toEqual({ industry: '制造业', price: 88 })
    expect(flow.canConfirmListingUpload.value).toBe(true)
  })
})
