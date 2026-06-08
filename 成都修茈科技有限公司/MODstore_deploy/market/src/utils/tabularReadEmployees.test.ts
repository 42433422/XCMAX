import { describe, expect, it } from 'vitest'
import {
  employeeAcceptsFileExtension,
  employeeFileMismatchHint,
  extractDocumentFullJsonText,
  extractEmployeeExecuteDiagnostics,
  extractEmployeeReadTextForLlm,
  formatEmployeeReadResultSummary,
  normalizeEmployeeExecuteEnvelope,
  parseEmployeeOutputDownloads,
  pickDocumentFullJsonDownload,
  pickPresentationFullJsonDownload,
  extractPresentationFullJsonText,
  resolveReadEmployeeForExtension,
  suggestEmployeeForUploadedFile,
} from './tabularReadEmployees'
import { isEmployeeExecuteFileExt } from './directAttachments'

describe('tabularReadEmployees', () => {
  it('suggestEmployeeForUploadedFile maps docx, pptx and json', () => {
    expect(suggestEmployeeForUploadedFile('docx')).toBe('word-full-read-employee')
    expect(suggestEmployeeForUploadedFile('pptx')).toBe('ppt-full-read-employee')
    expect(suggestEmployeeForUploadedFile('json')).toBe('json-report-employee')
    expect(employeeAcceptsFileExtension('json-report-employee', 'docx')).toBe(false)
    expect(employeeAcceptsFileExtension('word-full-read-employee', 'docx')).toBe(true)
    expect(employeeAcceptsFileExtension('ppt-full-read-employee', 'pptx')).toBe(true)
    expect(employeeAcceptsFileExtension('word-generate-employee', 'pptx')).toBe(false)
    expect(employeeAcceptsFileExtension('word-generate-employee', 'json')).toBe(true)
  })

  it('employeeFileMismatchHint names ppt read employee for pptx on generate employee', () => {
    const hint = employeeFileMismatchHint('word-generate-employee', 'pptx')
    expect(hint).toContain('ppt-full-read-employee')
    expect(hint).toContain('ppt-generate-employee')
  })

  it('maps extensions to read employee ids', () => {
    expect(resolveReadEmployeeForExtension('xlsx')).toBe('excel-full-read-employee')
    expect(resolveReadEmployeeForExtension('.csv')).toBe('csv-full-read-employee')
    expect(resolveReadEmployeeForExtension('pdf')).toBe('pdf-full-read-employee')
    expect(resolveReadEmployeeForExtension('docx')).toBe('word-full-read-employee')
    expect(resolveReadEmployeeForExtension('docm')).toBe('word-full-read-employee')
    expect(resolveReadEmployeeForExtension('txt')).toBeNull()
  })

  it('extractPresentationFullJsonText finds slides in execute envelope', () => {
    const text = extractPresentationFullJsonText({
      result: {
        outputs: [
          {
            handler: 'direct_python',
            ok: true,
            output: { ok: true, slides: [{ title: '封面', bullets: ['要点'] }] },
          },
        ],
      },
    })
    expect(text).toBeTruthy()
    expect(JSON.parse(text!)).toMatchObject({ slides: [{ title: '封面' }] })
  })

  it('pickPresentationFullJsonDownload', () => {
    const hit = pickPresentationFullJsonDownload([
      { jobId: 'j1', filename: 'outputs/presentation_full.json' },
    ])
    expect(hit?.filename).toContain('presentation_full.json')
  })

  it('extractDocumentFullJsonText finds nested paragraphs in execute envelope', () => {
    const text = extractDocumentFullJsonText({
      result: {
        outputs: [
          {
            handler: 'direct_python',
            ok: true,
            output: { ok: true, paragraphs: [{ text: 'a' }], tables: [] },
          },
        ],
      },
    })
    expect(text).toBeTruthy()
    expect(JSON.parse(text!)).toMatchObject({ paragraphs: [{ text: 'a' }] })
  })

  it('isEmployeeExecuteFileExt', () => {
    expect(isEmployeeExecuteFileExt('xls')).toBe(true)
    expect(isEmployeeExecuteFileExt('md')).toBe(false)
  })

  it('extractEmployeeReadTextForLlm prefers llm_context_text', () => {
    const t = extractEmployeeReadTextForLlm({ llm_context_text: '{"rows":[]}' })
    expect(t).toBe('{"rows":[]}')
  })

  it('normalizeEmployeeExecuteEnvelope merges nested result', () => {
    const env = normalizeEmployeeExecuteEnvelope({
      employee_id: 'word-full-read-employee',
      output_downloads: [{ job_id: 'j1', filename: 'document_full.json' }],
      result: {
        outputs: [{ handler: 'direct_python', ok: true, output: { ok: true, paragraph_count: 3 } }],
      },
    })
    expect(Array.isArray(env.outputs)).toBe(true)
    expect(env.output_downloads).toHaveLength(1)
    const { text } = formatEmployeeReadResultSummary('word-full-read-employee', '3.doc', {
      employee_id: 'word-full-read-employee',
      output_downloads: [{ job_id: 'j1', filename: 'document_full.json' }],
      result: {
        outputs: [{ handler: 'direct_python', ok: true, output: { ok: true, paragraph_count: 12, table_count: 1 } }],
      },
    })
    expect(text).toContain('自动')
    expect(text).toContain('段落')
  })

  it('extractEmployeeExecuteDiagnostics surfaces handler error', () => {
    const d = extractEmployeeExecuteDiagnostics({
      outputs: [
        {
          handler: 'direct_python',
          ok: false,
          output: { ok: false, error: '无法解析旧版 .doc', summary: '无法解析旧版 .doc' },
        },
      ],
    })
    expect(d.success).toBe(false)
    expect(d.error).toContain('.doc')
  })

  it('formatEmployeeReadResultSummary shows failure without json dump', () => {
    const { text } = formatEmployeeReadResultSummary('word-full-read-employee', '3.doc', {
      outputs: [{ handler: 'direct_python', ok: false, output: { ok: false, error: 'LibreOffice missing' } }],
    })
    expect(text).toContain('试跑失败')
    expect(text).not.toContain('```json')
  })

  it('formatEmployeeReadResultSummary for word read suggests report step', () => {
    const { text } = formatEmployeeReadResultSummary('word-full-read-employee', '3.doc', {
      ok: true,
      output_downloads: [{ job_id: 'j1', filename: 'document_full.json' }],
    })
    expect(text).toContain('自动')
    expect(pickDocumentFullJsonDownload(parseEmployeeOutputDownloads({
      output_downloads: [{ job_id: 'j1', filename: 'document_full.json' }],
    }))).toBeDefined()
  })

  it('parseEmployeeOutputDownloads', () => {
    const d = parseEmployeeOutputDownloads({
      output_downloads: [{ job_id: 'j1', filename: 'out.json', label: '结果' }],
    })
    expect(d).toEqual([{ jobId: 'j1', filename: 'out.json', label: '结果' }])
  })

  it('parseEmployeeOutputDownloads reads nested result.output_downloads', () => {
    const d = parseEmployeeOutputDownloads({
      result: {
        output_downloads: [{ job_id: 'j9', filename: 'generated_document.docx', label: 'Word 文档' }],
      },
    })
    expect(d).toEqual([
      { jobId: 'j9', filename: 'generated_document.docx', label: 'Word 文档' },
    ])
  })

  it('parseEmployeeOutputDownloads supports outputDownloads camelCase and files[]', () => {
    const d = parseEmployeeOutputDownloads({
      outputDownloads: [
        { jobId: 'j2', files: ['generated_document.docx', 'document_full.json'] },
      ],
    })
    expect(d.map((x) => x.filename)).toEqual(['generated_document.docx', 'document_full.json'])
  })
})
