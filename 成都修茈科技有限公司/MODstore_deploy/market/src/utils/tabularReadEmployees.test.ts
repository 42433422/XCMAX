import { describe, expect, it } from 'vitest'
import {
  employeeAcceptsFileExtension,
  employeeFileMismatchHint,
  extractDocumentFullJsonText,
  extractDirectPythonPayload,
  extractEmployeeExecuteDiagnostics,
  extractEmployeeReadTextForLlm,
  extractWordReadStats,
  formatEmployeeReadResultSummary,
  isGenerateEmployeeId,
  normalizeEmployeeExecuteEnvelope,
  parseEmployeeOutputDownloads,
  pickDocumentFullJsonDownload,
  pickPresentationFullJsonDownload,
  pickQuantitativeReportDownload,
  readEmployeeDisplayName,
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

  it('covers mismatch, display, and generate employee edge branches', () => {
    expect(isGenerateEmployeeId(' csv-generate-employee ')).toBe(true)
    expect(isGenerateEmployeeId('csv-full-read-employee')).toBe(false)
    expect(readEmployeeDisplayName('excel-generate-employee')).toBe('Excel 生成员')
    expect(employeeAcceptsFileExtension('word-full-read-employee', '')).toBe(false)
    expect(employeeAcceptsFileExtension('unknown-employee', 'txt')).toBe(false)
    expect(employeeFileMismatchHint('excel-generate-employee', 'xlsx')).toContain('excel-full-read-employee')
    expect(employeeFileMismatchHint('unknown-employee', 'xyz')).toContain('不支持 .xyz')
  })

  it('skips invalid direct python outputs before returning the first valid payload', () => {
    const payload = extractDirectPythonPayload({
      outputs: [
        null,
        'bad',
        { ok: false, output: { ok: true, value: 'skipped' } },
        { ok: true },
        { ok: true, output: 'not-object' },
        { ok: true, output: { ok: false, value: 'failed' } },
        { ok: true, output: { ok: true, value: 42 } },
      ],
    })

    expect(payload).toEqual({ ok: true, value: 42 })
  })

  it('handles embedded document and presentation json fallbacks and stringify failures', () => {
    const circularDoc: Record<string, unknown> = { paragraphs: [] }
    circularDoc.self = circularDoc
    const circularPresentation: Record<string, unknown> = { slides: [] }
    circularPresentation.self = circularPresentation

    expect(extractDocumentFullJsonText({ llm_context_text: '{"paragraphs":[]}' })).toBe('{"paragraphs":[]}')
    expect(extractDocumentFullJsonText({ outputs: [{ output: { items: [circularDoc] } }] })).toBeNull()
    expect(extractDocumentFullJsonText({ outputs: [{ output: circularDoc }] })).toBeNull()
    expect(extractPresentationFullJsonText({ llm_context_text: '{"slides":[]}' })).toBe('{"slides":[]}')
    expect(extractPresentationFullJsonText({ outputs: [{ output: { items: [circularPresentation] } }] })).toBeNull()
    expect(extractPresentationFullJsonText({ outputs: [{ output: circularPresentation }] })).toBeNull()
  })

  it('extracts word stats and parses downloads through fallback fields', () => {
    expect(extractWordReadStats({ outputs: [{ output: { paragraph_count: 7, table_count: 2 } }] })).toEqual({
      paragraphCount: 7,
      tableCount: 2,
      title: undefined,
    })
    expect(extractWordReadStats({ outputs: [{ output: { items: [{ paragraph_count: 3, table_count: 1 }] } }] })).toEqual({
      paragraphCount: 3,
      tableCount: 1,
      title: undefined,
    })

    const downloads = parseEmployeeOutputDownloads({
      output_downloads: [
        null,
        { job_id: ' ', filename: 'missing-job.txt' },
        { job_id: 'job-shared', filename: '' },
        { job_id: 'job-shared', files: [{ filename: 'from-file-object.txt' }] },
        { name: 'uses-shared-job.txt' },
        { jobId: 'job-shared', path: 'uses-path.txt', label: '  Path Label  ' },
        { jobId: 'job-shared', file: 'uses-file.txt' },
      ],
    })

    expect(downloads.map((d) => d.filename)).toEqual([
      'from-file-object.txt',
      'uses-shared-job.txt',
      'uses-path.txt',
      'uses-file.txt',
    ])
    expect(downloads[2].label).toBe('Path Label')
    expect(pickQuantitativeReportDownload([{ jobId: 'job', filename: 'reports/quantitative_report.html' }])).toBeTruthy()
  })

  it('extracts and truncates LLM text from nested fallback shapes', () => {
    const longJson = `{\n"rows": "${'x'.repeat(80)}"\n}`
    expect(extractEmployeeReadTextForLlm({ data: { text: longJson } }, 30)).toContain('已截断')

    const cyclic: Record<string, unknown> = {}
    cyclic.self = cyclic
    expect(extractEmployeeReadTextForLlm({ outputs: [{ output: cyclic }] })).toBe('')
    expect(extractEmployeeReadTextForLlm(cyclic)).toBe('')
  })

  it('formats summaries for warning, message, json, and generic preview branches', () => {
    const failed = formatEmployeeReadResultSummary('word-full-read-employee', 'legacy.doc', {
      ok: false,
      outputs: [
        { ok: false, output: { ok: false, error: 'LibreOffice missing', warnings: ['请安装转换器'] } },
      ],
    })
    expect(failed.text).toContain('提示')
    expect(failed.text).toContain('另存为 .docx')

    const okWithMessage = formatEmployeeReadResultSummary('csv-full-read-employee', 'data.csv', {
      message: '任务已完成',
      llm_context_text: '表格解析结果\n' + 'x'.repeat(60),
      output_downloads: [{ job_id: 'job', filename: 'rows.json' }],
    })
    expect(okWithMessage.text).toContain('任务已完成')
    expect(okWithMessage.text).toContain('解析摘要')

    const jsonItemsSummary = formatEmployeeReadResultSummary('json-report-employee', 'document_full.json', {
      items: { source_title: 'Items Doc', paragraph_count: 5, table_count: 4 },
      output_downloads: [{ job_id: 'job', filename: 'nested/quantitative_report.html' }],
      llm_context_text: '{"paragraphs":[]}',
    })
    expect(jsonItemsSummary.text).toContain('Items Doc')
    expect(jsonItemsSummary.text).toContain('HTML 量化报告已生成')
  })

  it('covers nested extraction, diagnostics, downloads, and fallback hint edge cases', () => {
    expect(employeeFileMismatchHint('unknown-employee', '')).toContain('不支持 .该')
    expect(employeeFileMismatchHint('pdf-generate-employee', 'pdf')).toContain('pdf-full-read-employee')

    const merged = normalizeEmployeeExecuteEnvelope({
      output_downloads: ['raw-download', { job_id: 'j1', filename: 'a.txt' }],
      result: {
        outputDownloads: ['raw-download', 'inner-download'],
        downloads: [{ job_id: 'j2', filename: 'b.txt' }],
      },
    })
    expect(merged.output_downloads).toEqual([
      'raw-download',
      { job_id: 'j1', filename: 'a.txt' },
      'inner-download',
      { job_id: 'j2', filename: 'b.txt' },
    ])

    const pptTooDeep = Array.from({ length: 14 }).reduce((node) => ({ data: node }), { slides: [] } as unknown)
    expect(extractPresentationFullJsonText(pptTooDeep)).toBeNull()
    expect(extractPresentationFullJsonText({ presentation_full: 'not-object' })).toBeNull()
    expect(extractPresentationFullJsonText({
      outputs: [null, 'bad', { output: { payload: { slides: [{ title: 'Nested' }] } } }],
    })).toContain('Nested')

    const docTooDeep = Array.from({ length: 14 }).reduce((node) => ({ data: node }), { paragraphs: [] } as unknown)
    expect(extractDocumentFullJsonText(docTooDeep)).toBeNull()
    expect(extractDocumentFullJsonText({ document_full: 'not-object' })).toBeNull()
    expect(extractDocumentFullJsonText({
      outputs: [null, 'bad', { output: { payload: { paragraphs: [{ text: 'Nested' }] } } }],
    })).toContain('Nested')

    expect(extractWordReadStats({
      llm_context_text: '{"title":"Root Title","paragraphs":[]}',
      outputs: [{ output: { ok: true } }],
    }).title).toBe('Root Title')

    expect(extractEmployeeExecuteDiagnostics({
      ok: false,
      summary: 'top summary only',
      outputs: [null, 'bad', { ok: true, output: { ok: true, warnings: [' '] } }],
    })).toMatchObject({
      success: false,
      error: 'top summary only',
      summary: 'top summary only',
    })

    const downloads = parseEmployeeOutputDownloads({
      output_downloads: [
        { job_id: 'job', filename: 'dir/file.txt' },
        { job_id: 'job', filename: 'dir/file.txt' },
      ],
    })
    expect(downloads).toEqual([{ jobId: 'job', filename: 'dir/file.txt', label: 'file.txt' }])

    expect(extractEmployeeReadTextForLlm({ llm_context_text: 'x'.repeat(50) }, 12)).toContain('已截断')
    const summary = formatEmployeeReadResultSummary('csv-full-read-employee', 'rows.csv', {
      output_downloads: [{ job_id: 'job', filename: 'dir/file.txt' }],
      outputs: [{ output: { text: '解析结果\n' + 'x'.repeat(80) } }],
    })
    expect(summary.text).toContain('file.txt')
    expect(summary.text).toContain('解析摘要')
  })
})
