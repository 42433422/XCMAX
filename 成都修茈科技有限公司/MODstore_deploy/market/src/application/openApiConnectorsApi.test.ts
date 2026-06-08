import { describe, expect, it, vi, beforeEach } from 'vitest'
import {
  importConnector,
  listConnectors,
  getConnector,
  deleteConnector,
  saveCredentials,
  deleteCredentials,
  toggleOperation,
  testOperation,
  publishWorkflowNode,
  listLogs,
} from './openApiConnectorsApi'
import { requestJson } from '../infrastructure/http/client'

vi.mock('../infrastructure/http/client', () => ({
  requestJson: vi.fn(),
}))

describe('openApiConnectorsApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('importConnector calls requestJson with POST', async () => {
    vi.mocked(requestJson).mockResolvedValue({ connector: {}, operations: [] })
    await importConnector({ name: 'test', spec_text: 'openapi: 3.0' })
    expect(requestJson).toHaveBeenCalledWith('/api/openapi-connectors/import', expect.objectContaining({ method: 'POST' }))
  })

  it('listConnectors calls requestJson', async () => {
    vi.mocked(requestJson).mockResolvedValue({ items: [] })
    await listConnectors()
    expect(requestJson).toHaveBeenCalledWith('/api/openapi-connectors/')
  })

  it('getConnector encodes id', async () => {
    vi.mocked(requestJson).mockResolvedValue({ connector: {}, operations: [], credential: {} })
    await getConnector('my/connector')
    expect(requestJson).toHaveBeenCalledWith('/api/openapi-connectors/my%2Fconnector')
  })

  it('deleteConnector calls requestJson with DELETE', async () => {
    vi.mocked(requestJson).mockResolvedValue({ ok: true })
    await deleteConnector(1)
    expect(requestJson).toHaveBeenCalledWith('/api/openapi-connectors/1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('saveCredentials calls requestJson with PUT', async () => {
    vi.mocked(requestJson).mockResolvedValue({ ok: true, credential: {} })
    await saveCredentials(1, 'bearer', { token: 'xxx' })
    expect(requestJson).toHaveBeenCalledWith('/api/openapi-connectors/1/credentials', expect.objectContaining({ method: 'PUT' }))
  })

  it('deleteCredentials calls requestJson with DELETE', async () => {
    vi.mocked(requestJson).mockResolvedValue({ ok: true })
    await deleteCredentials(1)
    expect(requestJson).toHaveBeenCalledWith('/api/openapi-connectors/1/credentials', expect.objectContaining({ method: 'DELETE' }))
  })

  it('toggleOperation calls requestJson with PATCH', async () => {
    vi.mocked(requestJson).mockResolvedValue({ ok: true, operation: {} })
    await toggleOperation(1, 'op1', true)
    expect(requestJson).toHaveBeenCalledWith('/api/openapi-connectors/1/operations/op1', expect.objectContaining({ method: 'PATCH' }))
  })

  it('testOperation calls requestJson with POST and defaults', async () => {
    vi.mocked(requestJson).mockResolvedValue({ ok: true })
    await testOperation(1, 'op1')
    const call = vi.mocked(requestJson).mock.calls[0] as any[]
    const body = JSON.parse(call[1].body as string)
    expect(body.params).toEqual({})
    expect(body.timeout).toBe(30)
  })

  it('testOperation passes custom payload', async () => {
    vi.mocked(requestJson).mockResolvedValue({ ok: true })
    await testOperation(1, 'op1', { params: { q: 'test' }, body: { data: 1 }, headers: { 'X-Custom': 'val' }, timeout: 60 })
    const call = vi.mocked(requestJson).mock.calls[0] as any[]
    const body = JSON.parse(call[1].body as string)
    expect(body.params).toEqual({ q: 'test' })
    expect(body.timeout).toBe(60)
  })

  it('publishWorkflowNode calls requestJson with POST', async () => {
    vi.mocked(requestJson).mockResolvedValue({ ok: true, node: {} })
    await publishWorkflowNode(1, { workflow_id: 2, operation_id: 'op1' })
    expect(requestJson).toHaveBeenCalledWith('/api/openapi-connectors/1/publish-workflow-node', expect.objectContaining({ method: 'POST' }))
  })

  it('listLogs passes limit and offset', async () => {
    vi.mocked(requestJson).mockResolvedValue({ items: [] })
    await listLogs(1, 10, 5)
    expect(requestJson).toHaveBeenCalledWith('/api/openapi-connectors/1/logs?limit=10&offset=5')
  })

  it('listLogs uses default limit and offset', async () => {
    vi.mocked(requestJson).mockResolvedValue({ items: [] })
    await listLogs(1)
    expect(requestJson).toHaveBeenCalledWith('/api/openapi-connectors/1/logs?limit=50&offset=0')
  })
})
