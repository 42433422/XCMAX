import { beforeEach, describe, expect, it, vi } from 'vitest'
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
  beforeEach(() => {
    vi.mocked(api.auditPackage).mockReset()
    vi.mocked(api.workflowSandboxRun).mockReset()
  })

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

  it('covers listing gate failures and fallback defaults', () => {
    const form = ref({ industry: '', price: -1 })
    const selectedFile = ref<File | null>(null)
    const flow = createFlow({
      form,
      selectedFile,
      resolvedWorkflowId: ref(0),
      listingHints: ref({ industryCoerced: '', priceFromManifest: Number.NaN }),
    })

    expect(flow.sandboxGateOk.value).toBe(false)
    expect(flow.canConfirmListingUpload.value).toBe(false)
    selectedFile.value = new File(['zip'], 'employee.zip')
    flow.publishWizardStep.value = 'listing'
    expect(flow.canConfirmListingUpload.value).toBe(false)
    flow.dockerLocalAck.value = true
    flow.auditLoading.value = true
    expect(flow.canConfirmListingUpload.value).toBe(false)
    flow.auditLoading.value = false
    flow.auditErr.value = 'audit failed'
    expect(flow.canConfirmListingUpload.value).toBe(false)
    flow.auditErr.value = ''
    flow.auditReport.value = { summary: { pass: false } }
    expect(flow.canConfirmListingUpload.value).toBe(false)
    flow.auditReport.value = { summary: { pass: true } }
    expect(flow.canConfirmListingUpload.value).toBe(false)
    form.value.industry = '通用'
    expect(flow.canConfirmListingUpload.value).toBe(false)
    form.value.price = 0
    expect(flow.canConfirmListingUpload.value).toBe(true)

    flow.publishWizardStep.value = 'compose'
    flow.goListingStep()
    expect(form.value).toEqual({ industry: '通用', price: 0 })
    expect(flow.publishWizardStep.value).toBe('listing')
    flow.backToTestingFromListing()
    expect(flow.publishWizardStep.value).toBe('testing')
    flow.backToComposeFromTesting()
    expect(flow.publishWizardStep.value).toBe('compose')
    expect(flow.dockerLocalAck.value).toBe(false)
    expect(flow.auditReport.value).toBeNull()
  })

  it('handles sandbox no-op, invalid input, validation failure, and API errors', async () => {
    const noFile = createFlow({ selectedFile: ref(null) })
    await noFile.runEmployeeWorkflowSandbox()
    expect(api.workflowSandboxRun).not.toHaveBeenCalled()

    const invalid = createFlow()
    invalid.wfSandboxInputJson.value = '{bad'
    await invalid.runEmployeeWorkflowSandbox()
    expect(invalid.wfSandboxErr.value).toContain('JSON')

    vi.mocked(api.workflowSandboxRun).mockResolvedValueOnce(sandboxStub(false, 'validate'))
    const validateFail = createFlow()
    validateFail.wfSandboxInputJson.value = '[]'
    await validateFail.runEmployeeWorkflowSandbox()
    expect(validateFail.wfSandboxOk.value).toBe(false)
    expect(api.workflowSandboxRun).toHaveBeenCalledTimes(1)

    vi.mocked(api.workflowSandboxRun).mockRejectedValueOnce(new Error('sandbox down'))
    const apiFail = createFlow()
    await apiFail.runEmployeeWorkflowSandbox()
    expect(apiFail.wfSandboxErr.value).toBe('sandbox down')
  })

  it('handles audit no-op, metadata variants, and API errors', async () => {
    const noGate = createFlow()
    await noGate.runFiveDimAuditClick('mod')
    expect(api.auditPackage).not.toHaveBeenCalled()

    vi.mocked(api.auditPackage).mockResolvedValueOnce({ summary: { pass: true } })
    const modAudit = createFlow({ resolvedWorkflowId: ref(0), linkedModId: ref('') })
    modAudit.dockerLocalAck.value = true
    await modAudit.runFiveDimAuditClick('mod')
    expect(api.auditPackage).toHaveBeenCalledWith(expect.any(File), {
      employee_config_v2: { identity: { id: 'agent-1' } },
      artifact: 'mod',
    })

    vi.mocked(api.auditPackage).mockRejectedValueOnce(new Error('audit down'))
    const fail = createFlow({ resolvedWorkflowId: ref(0) })
    fail.dockerLocalAck.value = true
    await fail.runFiveDimAuditClick('other')
    expect(fail.auditErr.value).toBe('audit down')

    const blocked = createFlow({ selectedFile: ref(null), resolvedWorkflowId: ref(0) })
    blocked.dockerLocalAck.value = true
    await blocked.runFiveDimAuditClick('employee_pack')
    expect(api.auditPackage).toHaveBeenCalledTimes(2)
  })
})
