import { createHash } from 'node:crypto'
import { expect, type Page } from '@playwright/test'
import { csrfHeaders } from './helpers'

const apiBase = (process.env.MOD_PILOT_FHD_API || process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5000').replace(/\/$/, '')

type EtlRun = {
  id: string
  status: string
  target_type: string
  summary: Record<string, number>
  receipt: Record<string, string>
  error?: { code: string; message: string } | null
}

type EtlRow = {
  final_action: string
  execution_status: string | null
  match_ref: string | null
  before: Record<string, unknown>
  after: Record<string, unknown>
}

async function jsonRequest(page: Page, path: string, method = 'GET', data?: unknown) {
  const response = await page.request.fetch(`${apiBase}${path}`, {
    method,
    data,
    headers: method === 'GET' ? undefined : await csrfHeaders(page.request, {}, apiBase),
    timeout: 30_000,
  })
  const text = await response.text()
  const body = JSON.parse(text || '{}')
  expect(response.ok(), `${method} ${path}: ${text}`).toBe(true)
  expect(body.success, `${method} ${path}: ${text}`).toBe(true)
  return body.data
}

async function waitForRun(page: Page, runId: string, status: string): Promise<EtlRun> {
  let run: EtlRun | undefined
  await expect.poll(async () => {
    run = await jsonRequest(page, `/api/etl/runs/${encodeURIComponent(runId)}`) as EtlRun
    if (run.status === 'failed' || run.status === 'interrupted') {
      throw new Error(`ETL ${runId} ${run.status}: ${JSON.stringify(run.error)}`)
    }
    return run.status
  }, { timeout: 90_000, intervals: [500, 1_000, 2_000] }).toBe(status)
  return run!
}

export async function importBusinessCsv(
  page: Page,
  target: 'customers' | 'products' | 'export_csv',
  csv: string,
  expectedAction: 'new' | 'update',
  allowedUpdateFields: string[] = [],
): Promise<{ run: EtlRun; row: EtlRow }> {
  const uploadHeaders = await csrfHeaders(page.request, {}, apiBase)
  delete uploadHeaders['Content-Type']
  const upload = await page.request.post(`${apiBase}/api/etl/uploads`, {
    headers: uploadHeaders,
    multipart: {
      file: {
        name: `e2e-${target}-${Date.now()}.csv`,
        mimeType: 'text/csv',
        buffer: Buffer.from(csv, 'utf8'),
      },
    },
    timeout: 30_000,
  })
  const uploadText = await upload.text()
  expect(upload.status(), uploadText).toBe(201)
  const uploadBody = JSON.parse(uploadText || '{}')
  expect(uploadBody.success, uploadText).toBe(true)
  expect(String(uploadBody.data?.sha256 || '')).toMatch(/^[a-f0-9]{64}$/)

  const preview = await jsonRequest(page, '/api/etl/runs/preview', 'POST', {
    upload_id: uploadBody.data.upload_id,
    target_type: target,
  }) as EtlRun
  expect(preview.target_type).toBe(target)
  let ready = await waitForRun(page, preview.id, 'preview_ready')
  if (allowedUpdateFields.length) {
    await jsonRequest(page, `/api/etl/runs/${preview.id}/draft`, 'PATCH', {
      allowed_update_fields: allowedUpdateFields,
    })
    ready = await waitForRun(page, preview.id, 'preview_ready')
  }
  expect(ready.summary[expectedAction], JSON.stringify(ready)).toBe(1)
  expect(ready.summary.error, JSON.stringify(ready)).toBe(0)

  const previewRows = await jsonRequest(page, `/api/etl/runs/${preview.id}/rows`) as { items: EtlRow[] }
  expect(previewRows.items).toHaveLength(1)
  expect(previewRows.items[0].final_action).toBe(expectedAction)
  await jsonRequest(page, `/api/etl/runs/${preview.id}/execute`, 'POST', {
    confirmed: true,
    valid_rows_only: false,
  })
  const completed = await waitForRun(page, preview.id, 'completed')
  expect(completed.summary.executed, JSON.stringify(completed)).toBe(1)
  const rows = await jsonRequest(page, `/api/etl/runs/${preview.id}/rows`) as { items: EtlRow[] }
  expect(rows.items).toHaveLength(1)
  expect(rows.items[0].execution_status).toBe('success')
  if (target !== 'export_csv') expect(rows.items[0].match_ref).toBeTruthy()
  return { run: completed, row: rows.items[0] }
}

export async function exportEtlRowsCsv(page: Page, csv: string): Promise<{ sha256: string; text: string }> {
  const { run } = await importBusinessCsv(page, 'export_csv', csv, 'new')
  const downloadUrl = String(run.receipt?.download_url || '')
  expect(downloadUrl).toMatch(/^\/api\/etl\/runs\/.+\/download$/)
  expect(String(run.receipt?.file_name || '')).toMatch(/\.csv$/)
  const response = await page.request.get(`${apiBase}${downloadUrl}`, { timeout: 30_000 })
  expect(response.status(), await response.text()).toBe(200)
  expect(response.headers()['content-type'] || '').toMatch(/text\/csv|application\/vnd\.ms-excel/)
  const bytes = await response.body()
  expect(bytes.byteLength).toBeGreaterThan(20)
  const sha256 = createHash('sha256').update(bytes).digest('hex')
  expect(sha256).toMatch(/^[a-f0-9]{64}$/)
  const replay = await page.request.get(`${apiBase}${downloadUrl}`, { timeout: 30_000 })
  expect(replay.status(), await replay.text()).toBe(200)
  expect(createHash('sha256').update(await replay.body()).digest('hex')).toBe(sha256)
  return { sha256, text: bytes.toString('utf8') }
}
