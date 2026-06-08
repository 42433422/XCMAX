import { describe, expect, it, vi } from 'vitest'
import { workbench, knowledge, openApiConnectors, customerService, butler } from './workbench'

vi.mock('./shared', () => ({
  req: vi.fn(() => Promise.resolve({})),
  authHeaders: vi.fn(() => ({ Authorization: 'Bearer test' })),
  requestBlob: vi.fn(() => Promise.resolve(new Blob())),
}))

import { req, requestBlob } from './shared'

const mReq = vi.mocked(req)
const mBlob = vi.mocked(requestBlob)

describe('workbench API', () => {
  beforeEach(() => { mReq.mockClear(); mBlob.mockClear() })

  it('workbenchResearchContext', async () => {
    await workbench.workbenchResearchContext({ q: 'test' })
    expect(mReq).toHaveBeenCalledWith('/api/workbench/research-context', expect.objectContaining({ method: 'POST' }))
  })

  it('workbenchStartSession', async () => {
    await workbench.workbenchStartSession({ task: 'x' })
    expect(mReq).toHaveBeenCalledWith('/api/workbench/sessions', expect.objectContaining({ method: 'POST' }))
  })

  it('workbenchStartSessionWithFiles', async () => {
    const file = new File(['content'], 'test.txt')
    await workbench.workbenchStartSessionWithFiles({ task: 'x' }, [file])
    expect(mReq).toHaveBeenCalledWith('/api/workbench/sessions', expect.objectContaining({ method: 'POST', body: expect.any(FormData) }))
  })

  it('workbenchStartScriptSession', async () => {
    const file = new File(['code'], 'script.py')
    await workbench.workbenchStartScriptSession({ name: 'test' }, [file])
    expect(mReq).toHaveBeenCalledWith('/api/workbench/script-sessions', expect.objectContaining({ method: 'POST' }))
  })

  it('workbenchGetSession', async () => {
    await workbench.workbenchGetSession('sess-1')
    expect(mReq).toHaveBeenCalledWith('/api/workbench/sessions/sess-1')
  })

  it('streamEmployeeAiDraft', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response())))
    const res = await workbench.streamEmployeeAiDraft('brief text')
    expect(res).toBeDefined()
    expect(fetch).toHaveBeenCalledWith('/api/workbench/employee-ai/draft', expect.objectContaining({ method: 'POST' }))
  })

  it('refineSystemPrompt', async () => {
    await workbench.refineSystemPrompt({ current_prompt: 'p', instruction: 'i' })
    expect(mReq).toHaveBeenCalledWith('/api/workbench/employee-ai/refine-prompt', expect.objectContaining({ method: 'POST' }))
  })

  it('workbenchEdgeTts', async () => {
    await workbench.workbenchEdgeTts('hello', 'voice1', 1.0)
    expect(mBlob).toHaveBeenCalledWith('/api/workbench/tts/edge', expect.objectContaining({ method: 'POST' }))
  })

  it('listStudioAssets with defaults', async () => {
    await workbench.listStudioAssets()
    expect(mReq).toHaveBeenCalledWith(expect.stringContaining('studio-assets'))
  })

  it('uploadStudioAsset', async () => {
    const file = new File(['data'], 'img.png')
    await workbench.uploadStudioAsset(file, { kind: 'image' })
    expect(mReq).toHaveBeenCalledWith('/api/workbench/studio-assets', expect.objectContaining({ method: 'POST' }))
  })

  it('deleteStudioAsset', async () => {
    await workbench.deleteStudioAsset(42)
    expect(mReq).toHaveBeenCalledWith('/api/workbench/studio-assets/42', expect.objectContaining({ method: 'DELETE' }))
  })

  it('patchStudioAssetMetadata', async () => {
    await workbench.patchStudioAssetMetadata(42, { key: 'val' })
    expect(mReq).toHaveBeenCalledWith('/api/workbench/studio-assets/42', expect.objectContaining({ method: 'PATCH' }))
  })

  it('downloadStudioAssetBlob', async () => {
    await workbench.downloadStudioAssetBlob(42)
    expect(mBlob).toHaveBeenCalledWith('/api/workbench/studio-assets/42/file')
  })
})

describe('knowledge API', () => {
  beforeEach(() => { mReq.mockClear() })

  it('knowledgeStatus', async () => {
    await knowledge.knowledgeStatus()
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/status')
  })

  it('knowledgeListDocuments', async () => {
    await knowledge.knowledgeListDocuments()
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/documents')
  })

  it('knowledgeUploadDocument', async () => {
    const file = new File(['text'], 'doc.pdf')
    await knowledge.knowledgeUploadDocument(file, { embeddingProvider: 'openai' })
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/documents', expect.objectContaining({ method: 'POST' }))
  })

  it('knowledgeDeleteDocument', async () => {
    await knowledge.knowledgeDeleteDocument('doc-1')
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/documents/doc-1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('knowledgeExtractText', async () => {
    const file = new File(['text'], 'doc.txt')
    await knowledge.knowledgeExtractText(file)
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/extract-text', expect.objectContaining({ method: 'POST' }))
  })

  it('knowledgeSearch', async () => {
    await knowledge.knowledgeSearch('query', 10)
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/search', expect.objectContaining({ method: 'POST' }))
  })

  it('knowledgeV2Status', async () => {
    await knowledge.knowledgeV2Status()
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/v2/status')
  })

  it('knowledgeV2ListCollections with params', async () => {
    await knowledge.knowledgeV2ListCollections({ ownerKind: 'employee', ownerId: 'e1' })
    expect(mReq).toHaveBeenCalledWith(expect.stringContaining('v2/collections'))
  })

  it('knowledgeV2CreateCollection', async () => {
    await knowledge.knowledgeV2CreateCollection({ name: 'test' })
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/v2/collections', expect.objectContaining({ method: 'POST' }))
  })

  it('knowledgeV2UpdateCollection', async () => {
    await knowledge.knowledgeV2UpdateCollection(1, { name: 'new' })
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/v2/collections/1', expect.objectContaining({ method: 'PATCH' }))
  })

  it('knowledgeV2DeleteCollection', async () => {
    await knowledge.knowledgeV2DeleteCollection(1)
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/v2/collections/1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('knowledgeV2ListDocuments', async () => {
    await knowledge.knowledgeV2ListDocuments(1)
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/v2/collections/1/documents')
  })

  it('knowledgeV2UploadDocument', async () => {
    const file = new File(['data'], 'f.txt')
    await knowledge.knowledgeV2UploadDocument(1, file)
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/v2/collections/1/documents', expect.objectContaining({ method: 'POST' }))
  })

  it('knowledgeV2DeleteDocument', async () => {
    await knowledge.knowledgeV2DeleteDocument(1, 'd1')
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/v2/collections/1/documents/d1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('knowledgeV2ShareCollection', async () => {
    await knowledge.knowledgeV2ShareCollection(1, { grantee_kind: 'user', grantee_id: 'u1' })
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/v2/collections/1/share', expect.objectContaining({ method: 'POST' }))
  })

  it('knowledgeV2Unshare', async () => {
    await knowledge.knowledgeV2Unshare(1, 2)
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/v2/collections/1/share/2', expect.objectContaining({ method: 'DELETE' }))
  })

  it('knowledgeV2Retrieve', async () => {
    await knowledge.knowledgeV2Retrieve({ query: 'test' })
    expect(mReq).toHaveBeenCalledWith('/api/knowledge/v2/retrieve', expect.objectContaining({ method: 'POST' }))
  })
})

describe('openApiConnectors API', () => {
  beforeEach(() => { mReq.mockClear() })

  it('openApiListConnectors', async () => {
    await openApiConnectors.openApiListConnectors()
    expect(mReq).toHaveBeenCalledWith('/api/openapi-connectors/')
  })

  it('openApiGetConnector', async () => {
    await openApiConnectors.openApiGetConnector(1)
    expect(mReq).toHaveBeenCalledWith('/api/openapi-connectors/1')
  })

  it('openApiImportConnector', async () => {
    await openApiConnectors.openApiImportConnector({ url: 'http://x' })
    expect(mReq).toHaveBeenCalledWith('/api/openapi-connectors/import', expect.objectContaining({ method: 'POST' }))
  })

  it('openApiDeleteConnector', async () => {
    await openApiConnectors.openApiDeleteConnector(1)
    expect(mReq).toHaveBeenCalledWith('/api/openapi-connectors/1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('openApiSaveCredentials', async () => {
    await openApiConnectors.openApiSaveCredentials(1, 'bearer', { token: 'x' })
    expect(mReq).toHaveBeenCalledWith('/api/openapi-connectors/1/credentials', expect.objectContaining({ method: 'PUT' }))
  })

  it('openApiDeleteCredentials', async () => {
    await openApiConnectors.openApiDeleteCredentials(1)
    expect(mReq).toHaveBeenCalledWith('/api/openapi-connectors/1/credentials', expect.objectContaining({ method: 'DELETE' }))
  })

  it('openApiToggleOperation', async () => {
    await openApiConnectors.openApiToggleOperation(1, 'op1', true)
    expect(mReq).toHaveBeenCalledWith('/api/openapi-connectors/1/operations/op1', expect.objectContaining({ method: 'PATCH' }))
  })

  it('openApiTestOperation', async () => {
    await openApiConnectors.openApiTestOperation(1, 'op1', {})
    expect(mReq).toHaveBeenCalledWith('/api/openapi-connectors/1/operations/op1/test', expect.objectContaining({ method: 'POST' }))
  })

  it('openApiPublishWorkflowNode', async () => {
    await openApiConnectors.openApiPublishWorkflowNode(1, {})
    expect(mReq).toHaveBeenCalledWith('/api/openapi-connectors/1/publish-workflow-node', expect.objectContaining({ method: 'POST' }))
  })

  it('openApiListLogs', async () => {
    await openApiConnectors.openApiListLogs(1, 10, 0)
    expect(mReq).toHaveBeenCalledWith(expect.stringContaining('logs'))
  })
})

describe('customerService API', () => {
  beforeEach(() => { mReq.mockClear() })

  it('customerServiceChat', async () => {
    await customerService.customerServiceChat({ message: 'hi' })
    expect(mReq).toHaveBeenCalledWith('/api/customer-service/chat', expect.objectContaining({ method: 'POST' }))
  })

  it('customerServiceSessions', async () => {
    await customerService.customerServiceSessions()
    expect(mReq).toHaveBeenCalledWith('/api/customer-service/sessions')
  })

  it('customerServiceSessionDetail', async () => {
    await customerService.customerServiceSessionDetail(1)
    expect(mReq).toHaveBeenCalledWith('/api/customer-service/sessions/1')
  })

  it('customerServiceTickets with status', async () => {
    await customerService.customerServiceTickets('open')
    expect(mReq).toHaveBeenCalledWith(expect.stringContaining('tickets?status=open'))
  })

  it('customerServiceTicketDetail', async () => {
    await customerService.customerServiceTicketDetail(1)
    expect(mReq).toHaveBeenCalledWith('/api/customer-service/tickets/1')
  })

  it('customerServiceActions', async () => {
    await customerService.customerServiceActions(1)
    expect(mReq).toHaveBeenCalledWith(expect.stringContaining('actions'))
  })

  it('customerServiceStandards', async () => {
    await customerService.customerServiceStandards()
    expect(mReq).toHaveBeenCalledWith('/api/customer-service/standards')
  })

  it('customerServiceCreateStandard', async () => {
    await customerService.customerServiceCreateStandard({ name: 's1' })
    expect(mReq).toHaveBeenCalledWith('/api/customer-service/standards', expect.objectContaining({ method: 'POST' }))
  })

  it('customerServiceUpdateStandard', async () => {
    await customerService.customerServiceUpdateStandard(1, { name: 's2' })
    expect(mReq).toHaveBeenCalledWith('/api/customer-service/standards/1', expect.objectContaining({ method: 'PUT' }))
  })

  it('customerServiceIntegrations', async () => {
    await customerService.customerServiceIntegrations()
    expect(mReq).toHaveBeenCalledWith('/api/customer-service/integrations')
  })

  it('customerServiceCreateIntegration', async () => {
    await customerService.customerServiceCreateIntegration({ type: 'slack' })
    expect(mReq).toHaveBeenCalledWith('/api/customer-service/integrations', expect.objectContaining({ method: 'POST' }))
  })

  it('customerServiceUpdateIntegration', async () => {
    await customerService.customerServiceUpdateIntegration(1, { type: 'wechat' })
    expect(mReq).toHaveBeenCalledWith('/api/customer-service/integrations/1', expect.objectContaining({ method: 'PUT' }))
  })
})

describe('butler API', () => {
  beforeEach(() => { mReq.mockClear() })

  it('agentButlerChat', async () => {
    await butler.agentButlerChat({ messages: [] })
    expect(mReq).toHaveBeenCalledWith('/api/agent/butler/chat', expect.objectContaining({ method: 'POST' }))
  })

  it('agentButlerChatStream', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response())))
    const res = await butler.agentButlerChatStream({ messages: [] })
    expect(res).toBeDefined()
    expect(fetch).toHaveBeenCalledWith('/api/agent/butler/chat/stream', expect.objectContaining({ method: 'POST' }))
  })

  it('listButlerSkills', async () => {
    await butler.listButlerSkills()
    expect(mReq).toHaveBeenCalledWith('/api/agent/butler/skills')
  })

  it('recordButlerAction', async () => {
    await butler.recordButlerAction({ route: '/', action: 'click', risk: 'low', status: 'success' })
    expect(mReq).toHaveBeenCalledWith('/api/agent/butler/actions', expect.objectContaining({ method: 'POST' }))
  })

  it('updateButlerSkillActive', async () => {
    await butler.updateButlerSkillActive(1, true)
    expect(mReq).toHaveBeenCalledWith('/api/agent/butler/skills/1', expect.objectContaining({ method: 'PATCH' }))
  })

  it('butlerOrchestrateStart', async () => {
    await butler.butlerOrchestrateStart({ target_type: 'mod', target_id: 'm1', brief: 'test' })
    expect(mReq).toHaveBeenCalledWith('/api/agent/butler/orchestrate', expect.objectContaining({ method: 'POST' }))
  })

  it('butlerAllHandsReportStartSession', async () => {
    await butler.butlerAllHandsReportStartSession({ employee_ids: ['e1'] })
    expect(mReq).toHaveBeenCalledWith('/api/agent/butler/all-hands-report/sessions', expect.objectContaining({ method: 'POST' }))
  })

  it('butlerAllHandsReport', async () => {
    await butler.butlerAllHandsReport({ employee_ids: ['e1'] })
    expect(mReq).toHaveBeenCalledWith('/api/agent/butler/all-hands-report', expect.objectContaining({ method: 'POST' }))
  })
})
