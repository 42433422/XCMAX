import { describe, expect, it } from 'vitest'
import {
  directFileExt,
  directFileKind,
  directFileKindLabel,
  formatDirectFileSize,
  normalizeDirectAttachmentError,
  resolveDirectAttachmentOutcome,
} from './directAttachments'

describe('directAttachments', () => {
  it('detects attachment extension and display type', () => {
    expect(directFileExt('2025年12月收入.xlsx')).toBe('xlsx')
    expect(directFileKind('2025年12月收入.xlsx')).toBe('excel')
    expect(directFileKindLabel(directFileKind('报价单.pdf'))).toBe('PDF')
    expect(directFileKind('README.md')).toBe('text')
    expect(directFileKind('data.json')).toBe('json')
  })

  it('keeps extracted xlsx sendable when knowledge indexing fails', () => {
    const outcome = resolveDirectAttachmentOutcome({
      extractedText: '月份 | 收入\n2025-12 | 120000',
      uploadError: new Error('chromadb unavailable'),
    })

    expect(outcome.status).toBe('inline')
    expect(outcome.canSend).toBe(true)
    expect(outcome.extractedText).toContain('2025-12')
    expect(outcome.ingestError).toContain('chromadb unavailable')
  })

  it('marks attachment as ready when document id is returned', () => {
    const outcome = resolveDirectAttachmentOutcome({
      extractedText: '门店 | 收入\nA | 100',
      docId: 'doc_123',
    })

    expect(outcome.status).toBe('ready')
    expect(outcome.canSend).toBe(true)
    expect(outcome.docId).toBe('doc_123')
  })

  it('reports extraction failure as not sendable content', () => {
    const outcome = resolveDirectAttachmentOutcome({
      extractError: new Error('服务器未安装 openpyxl，暂不能解析 XLSX'),
    })

    expect(outcome.status).toBe('error')
    expect(outcome.canSend).toBe(false)
    expect(outcome.error).toContain('openpyxl')
  })

  it('formats sizes and normalizes empty-text errors', () => {
    expect(formatDirectFileSize(900)).toBe('900 B')
    expect(formatDirectFileSize(2048)).toBe('2.0 KB')
    expect(normalizeDirectAttachmentError('未能从文件中提取有效文本')).toContain('未能从文件中提取有效文本')
  })
})
