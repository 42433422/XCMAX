/**
 * 办公对接服务端调用（拆分自 composables/useChatOfficeDocking.ts，行为保持一致）：
 * 送货单 ETL 预览/执行、知识库入库、考勤库入库。
 */
import { primeCsrfCookie } from '@/api/core'
import { apiFetch } from '@/utils/apiBase'
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import type { ChatOfficeDockingReviewItem, ShipmentEtlNotePreview, ShipmentEtlPreview } from './officeDockingShared'

export async function previewShipmentExcelEtl(filePath: string, workspaceRoot?: string): Promise<ShipmentEtlPreview | null> {
  const path = asString(filePath).trim()
  if (!path) return null
  await primeCsrfCookie()
  const fd = new FormData()
  fd.append('file_path', path)
  if (workspaceRoot) fd.append('workspace_root', workspaceRoot)
  fd.append('include_ledger', 'auto')
  const res = await apiFetch('/api/excel/data/shipment-etl/preview', { method: 'POST', body: fd })
  const body = await res.json().catch(() => ({}))
  const data = asRecord(body)
  if (!res.ok || data.success === false) return null
  const notes = asArray<ShipmentEtlNotePreview>(data.notes)
  if (!notes.length) return null
  return { ...data, notes, note_count: Number(data.note_count || notes.length) || notes.length }
}

export async function executeShipmentExcelEtl(item: ChatOfficeDockingReviewItem): Promise<Record<string, unknown>> {
  if (!item.upload?.file_path) throw new Error('缺少已上传文件路径')
  await primeCsrfCookie()
  const fd = new FormData()
  fd.append('file_path', item.upload.file_path)
  if (item.upload.workspace_root) fd.append('workspace_root', item.upload.workspace_root)
  fd.append('import_products', '1')
  fd.append('import_shipments', '1')
  fd.append('idempotent', '1')
  fd.append('include_ledger', '0')
  fd.append('confirm_ledger', '0')
  if (item.shipmentEtlPreview?.notes?.length) {
    fd.append('notes_json', JSON.stringify(item.shipmentEtlPreview.notes))
  }
  const res = await apiFetch('/api/excel/data/shipment-etl/execute', { method: 'POST', body: fd })
  const body = await res.json().catch(() => ({}))
  const data = asRecord(body)
  if (!res.ok || data.success === false) {
    throw new Error(String(data.message || data.error || `送货单 ETL 失败 HTTP ${res.status}`))
  }
  return data
}

export async function ingestKnowledge(item: ChatOfficeDockingReviewItem): Promise<void> {
  const text = item.knowledgeText.trim()
  if (!text) throw new Error('知识库文本为空')
  await primeCsrfCookie()
  // Governed Persy dataset path (legacy /ingest still dual-writes server-side).
  const res = await apiFetch('/api/knowledge/v1/datasets/persy-knowledge/documents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source: item.fileName,
      text,
      chunk_strategy: 'semantic',
      metadata: { entrypoint: 'chat_office_docking' },
    }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body?.success === false) {
    throw new Error(String(body?.message || '知识库入库失败'))
  }
}

export async function ingestAttendanceDatabase(item: ChatOfficeDockingReviewItem): Promise<Record<string, unknown>> {
  if (!item.upload?.file_path) throw new Error('缺少已上传文件路径')
  await primeCsrfCookie()
  const res = await apiFetch('/api/mod/taiyangniao-pro/attendance/import-workbook', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      file_path: item.upload.file_path,
      workspace_root: item.upload.workspace_root,
      source_name: item.fileName,
      sync_ui_tables: true,
    }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok || body?.success === false) {
    throw new Error(String(body?.error || body?.message || `考勤入库失败 HTTP ${res.status}`))
  }
  return asRecord(body?.data || body)
}
