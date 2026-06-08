import { requestJson } from '../infrastructure/http/client'

export type OpenApiAuthType =
  | 'none'
  | 'api_key'
  | 'bearer'
  | 'basic'
  | 'oauth2_client_credentials'

export interface OpenApiConnectorSummary {
  id: number
  name: string
  description: string
  base_url: string
  title: string
  spec_version: string
  spec_hash: string
  status: string
  operation_count: number
  generated_version: number
  last_error: string
  created_at: string | null
  updated_at: string | null
}

export interface OpenApiOperationSummary {
  operation_id: string
  method: string
  path: string
  summary: string
  tags: string[]
  request_schema: Record<string, unknown>
  response_schema: Record<string, unknown>
  generated_symbol: string
  enabled: boolean
}

export interface OpenApiCredentialView {
  auth_type: OpenApiAuthType
  configured: boolean
  config_preview: Record<string, string>
  updated_at?: string | null
}

export interface OpenApiCallLogEntry {
  id: number
  operation_id: string
  method: string
  path: string
  status_code: number | null
  duration_ms: number
  request_summary: string
  response_summary: string
  error: string
  source: string
  created_at: string | null
}

export interface OpenApiTestResult {
  ok: boolean
  status_code: number | null
  body: unknown
  headers: Record<string, string>
  error: string
  duration_ms: number
  operation_id: string
  url: string
  method: string
}

export interface ImportConnectorPayload {
  name: string
  description?: string
  spec_text?: string
  spec_url?: string
  base_url_override?: string
}

export interface ImportConnectorResponse {
  connector: OpenApiConnectorSummary
  operations: OpenApiOperationSummary[]
}

export interface ConnectorDetailResponse {
  connector: OpenApiConnectorSummary
  operations: OpenApiOperationSummary[]
  credential: OpenApiCredentialView
}

export function importConnector(
  payload: ImportConnectorPayload,
): Promise<ImportConnectorResponse> {
  return requestJson('/api/openapi-connectors/import', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listConnectors(): Promise<{ items: OpenApiConnectorSummary[] }> {
  return requestJson('/api/openapi-connectors/')
}

export function getConnector(id: number | string): Promise<ConnectorDetailResponse> {
  return requestJson(`/api/openapi-connectors/${encodeURIComponent(String(id))}`)
}

export function deleteConnector(id: number | string): Promise<{ ok: boolean }> {
  return requestJson(`/api/openapi-connectors/${encodeURIComponent(String(id))}`, {
    method: 'DELETE',
  })
}

export function saveCredentials(
  id: number | string,
  authType: OpenApiAuthType,
  config: Record<string, unknown>,
): Promise<{ ok: boolean; credential: OpenApiCredentialView }> {
  return requestJson(
    `/api/openapi-connectors/${encodeURIComponent(String(id))}/credentials`,
    {
      method: 'PUT',
      body: JSON.stringify({ auth_type: authType, config }),
    },
  )
}

export function deleteCredentials(id: number | string): Promise<{ ok: boolean }> {
  return requestJson(
    `/api/openapi-connectors/${encodeURIComponent(String(id))}/credentials`,
    { method: 'DELETE' },
  )
}

export function toggleOperation(
  id: number | string,
  operationId: string,
  enabled: boolean,
): Promise<{ ok: boolean; operation: OpenApiOperationSummary }> {
  return requestJson(
    `/api/openapi-connectors/${encodeURIComponent(String(id))}/operations/${encodeURIComponent(operationId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    },
  )
}

export interface TestCallPayload {
  params?: Record<string, unknown>
  body?: unknown
  headers?: Record<string, string>
  timeout?: number
}

export function testOperation(
  id: number | string,
  operationId: string,
  payload: TestCallPayload = {},
): Promise<OpenApiTestResult> {
  return requestJson(
    `/api/openapi-connectors/${encodeURIComponent(String(id))}/operations/${encodeURIComponent(operationId)}/test`,
    {
      method: 'POST',
      body: JSON.stringify({
        params: payload.params || {},
        body: payload.body ?? null,
        headers: payload.headers || {},
        timeout: payload.timeout ?? 30,
      }),
    },
  )
}

export interface PublishWorkflowNodePayload {
  workflow_id: number | string
  operation_id: string
  name?: string
  input_mapping?: Record<string, unknown>
  output_mapping?: Record<string, unknown>
  timeout_seconds?: number
  retry_count?: number
  position_x?: number
  position_y?: number
}

export function publishWorkflowNode(
  id: number | string,
  payload: PublishWorkflowNodePayload,
): Promise<{ ok: boolean; node: Record<string, unknown> }> {
  return requestJson(
    `/api/openapi-connectors/${encodeURIComponent(String(id))}/publish-workflow-node`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
}

export function listLogs(
  id: number | string,
  limit = 50,
  offset = 0,
): Promise<{ items: OpenApiCallLogEntry[] }> {
  return requestJson(
    `/api/openapi-connectors/${encodeURIComponent(String(id))}/logs?limit=${limit}&offset=${offset}`,
  )
}
