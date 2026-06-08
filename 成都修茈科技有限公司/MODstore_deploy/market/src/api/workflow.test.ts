import { describe, expect, it, vi, beforeEach } from 'vitest'
import { scriptWorkflows, workflow } from './workflow'
import { req, authHeaders, fetchZipBlob } from './shared'

vi.mock('./shared', () => ({
  req: vi.fn(),
  authHeaders: vi.fn(() => ({ Authorization: 'Bearer test' })),
  fetchZipBlob: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('scriptWorkflows api', () => {
  it('listScriptWorkflows calls req without status', async () => {
    vi.mocked(req).mockResolvedValue([])
    await scriptWorkflows.listScriptWorkflows()
    expect(req).toHaveBeenCalledWith('/api/script-workflows')
  })

  it('listScriptWorkflows passes status', async () => {
    vi.mocked(req).mockResolvedValue([])
    await scriptWorkflows.listScriptWorkflows('active')
    expect(req).toHaveBeenCalledWith('/api/script-workflows?status=active')
  })

  it('getScriptWorkflow calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await scriptWorkflows.getScriptWorkflow(1)
    expect(req).toHaveBeenCalledWith('/api/script-workflows/1')
  })

  it('updateScriptWorkflow calls req with PUT', async () => {
    vi.mocked(req).mockResolvedValue({})
    await scriptWorkflows.updateScriptWorkflow(1, { name: 'test' })
    expect(req).toHaveBeenCalledWith('/api/script-workflows/1', expect.objectContaining({ method: 'PUT' }))
  })

  it('deleteScriptWorkflow calls req with DELETE', async () => {
    vi.mocked(req).mockResolvedValue({})
    await scriptWorkflows.deleteScriptWorkflow(1)
    expect(req).toHaveBeenCalledWith('/api/script-workflows/1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('sandboxRunScriptWorkflow calls req with POST and FormData', async () => {
    vi.mocked(req).mockResolvedValue({})
    const file = new File(['content'], 'test.csv')
    await scriptWorkflows.sandboxRunScriptWorkflow(1, [file])
    expect(req).toHaveBeenCalledWith('/api/script-workflows/1/sandbox-run', expect.objectContaining({ method: 'POST' }))
  })

  it('runScriptWorkflow calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    const file = new File(['content'], 'test.csv')
    await scriptWorkflows.runScriptWorkflow(1, [file])
    expect(req).toHaveBeenCalledWith('/api/script-workflows/1/run', expect.objectContaining({ method: 'POST' }))
  })

  it('activateScriptWorkflow calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await scriptWorkflows.activateScriptWorkflow(1)
    expect(req).toHaveBeenCalledWith('/api/script-workflows/1/activate', expect.objectContaining({ method: 'POST' }))
  })

  it('deactivateScriptWorkflow calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await scriptWorkflows.deactivateScriptWorkflow(1)
    expect(req).toHaveBeenCalledWith('/api/script-workflows/1/deactivate', expect.objectContaining({ method: 'POST' }))
  })

  it('listScriptWorkflowRuns passes mode', async () => {
    vi.mocked(req).mockResolvedValue([])
    await scriptWorkflows.listScriptWorkflowRuns(1, 'sandbox')
    expect(req).toHaveBeenCalledWith('/api/script-workflows/1/runs?mode=sandbox')
  })

  it('listScriptWorkflowVersions calls req', async () => {
    vi.mocked(req).mockResolvedValue([])
    await scriptWorkflows.listScriptWorkflowVersions(1)
    expect(req).toHaveBeenCalledWith('/api/script-workflows/1/versions')
  })

  it('commitScriptWorkflowSession calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await scriptWorkflows.commitScriptWorkflowSession('sid1', { name: 'test' })
    expect(req).toHaveBeenCalledWith('/api/script-workflows/sessions/sid1/commit', expect.objectContaining({ method: 'POST' }))
  })

  it('getScriptWorkflowSession calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await scriptWorkflows.getScriptWorkflowSession('sid1')
    expect(req).toHaveBeenCalledWith('/api/script-workflows/sessions/sid1')
  })
})

describe('workflow api', () => {
  it('listWorkflows calls req', async () => {
    vi.mocked(req).mockResolvedValue([])
    await workflow.listWorkflows()
    expect(req).toHaveBeenCalledWith('/api/workflow/')
  })

  it('listESkills calls req', async () => {
    vi.mocked(req).mockResolvedValue([])
    await workflow.listESkills()
    expect(req).toHaveBeenCalledWith('/api/eskills')
  })

  it('createESkill calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.createESkill({ name: 'test' })
    expect(req).toHaveBeenCalledWith('/api/eskills', expect.objectContaining({ method: 'POST' }))
  })

  it('runESkill calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.runESkill(1, { input: 'test' })
    expect(req).toHaveBeenCalledWith('/api/eskills/1/run', expect.objectContaining({ method: 'POST' }))
  })

  it('listEmployeeEligibleWorkflows calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.listEmployeeEligibleWorkflows()
    expect(req).toHaveBeenCalledWith('/api/workflow/employee-eligible')
  })

  it('listWorkflowsByEmployee encodes employeeId', async () => {
    vi.mocked(req).mockResolvedValue([])
    await workflow.listWorkflowsByEmployee('emp/1')
    expect(req).toHaveBeenCalledWith('/api/workflow/by-employee?employee_id=emp%2F1')
  })

  it('getWorkflow calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.getWorkflow(1)
    expect(req).toHaveBeenCalledWith('/api/workflow/1')
  })

  it('createWorkflow calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.createWorkflow('name', 'desc')
    expect(req).toHaveBeenCalledWith('/api/workflow/', expect.objectContaining({ method: 'POST' }))
  })

  it('updateWorkflow calls req with PUT', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.updateWorkflow(1, 'name', 'desc', true)
    expect(req).toHaveBeenCalledWith('/api/workflow/1', expect.objectContaining({ method: 'PUT' }))
  })

  it('deleteWorkflow calls req with DELETE', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.deleteWorkflow(1)
    expect(req).toHaveBeenCalledWith('/api/workflow/1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('addWorkflowNode calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.addWorkflowNode(1, 'start', 'Start', {}, 100, 200)
    expect(req).toHaveBeenCalledWith('/api/workflow/1/nodes', expect.objectContaining({ method: 'POST' }))
  })

  it('updateWorkflowNode calls req with PUT', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.updateWorkflowNode(1, 'Updated', {}, 100, 200)
    expect(req).toHaveBeenCalledWith('/api/workflow/nodes/1', expect.objectContaining({ method: 'PUT' }))
  })

  it('deleteWorkflowNode calls req with DELETE', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.deleteWorkflowNode(1)
    expect(req).toHaveBeenCalledWith('/api/workflow/nodes/1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('addWorkflowEdge calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.addWorkflowEdge(1, 1, 2, 'true')
    expect(req).toHaveBeenCalledWith('/api/workflow/1/edges', expect.objectContaining({ method: 'POST' }))
  })

  it('deleteWorkflowEdge calls req with DELETE', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.deleteWorkflowEdge(1)
    expect(req).toHaveBeenCalledWith('/api/workflow/edges/1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('executeWorkflow calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.executeWorkflow(1, { input: 'test' })
    expect(req).toHaveBeenCalledWith('/api/workflow/1/execute', expect.objectContaining({ method: 'POST' }))
  })

  it('workflowValidate calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.workflowValidate(1)
    expect(req).toHaveBeenCalledWith('/api/workflow/1/validate')
  })

  it('workflowSandboxRun calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.workflowSandboxRun(1, {})
    expect(req).toHaveBeenCalledWith('/api/workflow/1/sandbox-run', expect.objectContaining({ method: 'POST' }))
  })

  it('listWorkflowExecutions passes limit and offset', async () => {
    vi.mocked(req).mockResolvedValue([])
    await workflow.listWorkflowExecutions(1, 10, 5)
    expect(req).toHaveBeenCalledWith('/api/workflow/1/executions?limit=10&offset=5')
  })

  it('listWorkflowTriggers calls req', async () => {
    vi.mocked(req).mockResolvedValue([])
    await workflow.listWorkflowTriggers(1)
    expect(req).toHaveBeenCalledWith('/api/workflow/1/triggers')
  })

  it('createWorkflowTrigger calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.createWorkflowTrigger(1, { type: 'webhook' })
    expect(req).toHaveBeenCalledWith('/api/workflow/1/triggers', expect.objectContaining({ method: 'POST' }))
  })

  it('deleteWorkflowTrigger calls req with DELETE', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.deleteWorkflowTrigger(1, 2)
    expect(req).toHaveBeenCalledWith('/api/workflow/1/triggers/2', expect.objectContaining({ method: 'DELETE' }))
  })

  it('workflowWebhookRun calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.workflowWebhookRun(1, { data: 'test' })
    expect(req).toHaveBeenCalledWith('/api/workflow/1/webhook-run', expect.objectContaining({ method: 'POST' }))
  })

  it('publishWorkflowVersion calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.publishWorkflowVersion(1, 'release')
    expect(req).toHaveBeenCalledWith('/api/workflow/1/versions/publish', expect.objectContaining({ method: 'POST' }))
  })

  it('listWorkflowVersions passes limit and offset', async () => {
    vi.mocked(req).mockResolvedValue([])
    await workflow.listWorkflowVersions(1, 10, 5)
    expect(req).toHaveBeenCalledWith('/api/workflow/1/versions?limit=10&offset=5')
  })

  it('getWorkflowVersion calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.getWorkflowVersion(1, 2)
    expect(req).toHaveBeenCalledWith('/api/workflow/1/versions/2')
  })

  it('rollbackWorkflowVersion calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.rollbackWorkflowVersion(1, 2)
    expect(req).toHaveBeenCalledWith('/api/workflow/1/versions/2/rollback', expect.objectContaining({ method: 'POST' }))
  })

  it('getExecution calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await workflow.getExecution(1)
    expect(req).toHaveBeenCalledWith('/api/workflow/executions/1')
  })
})
