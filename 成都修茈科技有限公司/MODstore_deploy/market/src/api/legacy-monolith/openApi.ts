// OpenAPI 连接器域端点（自 legacyMonolith.ts 拆分，方法体保持不变）
import { req } from './shared'

export const openApiEndpoints = {
  openApiListConnectors: () => req('/api/openapi-connectors/'),
  openApiGetConnector: (id: number | string) => req(`/api/openapi-connectors/${encodeURIComponent(String(id))}`),
  openApiImportConnector: (payload: unknown) =>
    req('/api/openapi-connectors/import', { method: 'POST', body: JSON.stringify(payload) }),
  openApiDeleteConnector: (id: number | string) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}`, { method: 'DELETE' }),
  openApiSaveCredentials: (id: number | string, authType: string, config: unknown) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/credentials`, {
      method: 'PUT',
      body: JSON.stringify({ auth_type: authType, config }),
    }),
  openApiDeleteCredentials: (id: number | string) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/credentials`, { method: 'DELETE' }),
  openApiToggleOperation: (id: number | string, operationId: string, enabled: boolean) =>
    req(
      `/api/openapi-connectors/${encodeURIComponent(String(id))}/operations/${encodeURIComponent(operationId)}`,
      { method: 'PATCH', body: JSON.stringify({ enabled }) },
    ),
  openApiTestOperation: (id: number | string, operationId: string, payload: unknown) =>
    req(
      `/api/openapi-connectors/${encodeURIComponent(String(id))}/operations/${encodeURIComponent(operationId)}/test`,
      { method: 'POST', body: JSON.stringify(payload || {}) },
    ),
  openApiPublishWorkflowNode: (id: number | string, payload: unknown) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/publish-workflow-node`, {
      method: 'POST',
      body: JSON.stringify(payload || {}),
    }),
  openApiListLogs: (id: number | string, limit = 50, offset = 0) =>
    req(`/api/openapi-connectors/${encodeURIComponent(String(id))}/logs?limit=${limit}&offset=${offset}`),
}
