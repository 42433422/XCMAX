import { afterEach, describe, expect, it, vi } from 'vitest'

const mockApi = vi.hoisted(() => ({
  employeeExecuteFile: vi.fn(),
  employeeOutputDownload: vi.fn(),
}))

vi.mock('./api', () => ({ api: mockApi }))

afterEach(() => {
  mockApi.employeeExecuteFile.mockReset()
  mockApi.employeeOutputDownload.mockReset()
  vi.restoreAllMocks()
})

describe('office employee runner and tabular employee coverage', () => {
  it('normalizes employee ids, file acceptance, diagnostics, downloads, and summaries', async () => {
    const tabular = await import('./utils/tabularReadEmployees')

    expect(tabular.resolveReadEmployeeForExtension('.DOCX')).toBe('word-full-read-employee')
    expect(tabular.resolveReadEmployeeForExtension('unknown')).toBeNull()
    expect(tabular.isEmployeeExecuteFileExt('pdf')).toBe(true)
    expect(tabular.isGenerateEmployeeId(' word-generate-employee ')).toBe(true)
    expect(tabular.employeeAcceptsFileExtension('json-report-employee', 'json')).toBe(true)
    expect(tabular.employeeAcceptsFileExtension('word-generate-employee', 'docx')).toBe(true)
    expect(tabular.employeeAcceptsFileExtension('word-generate-employee', 'pdf')).toBe(false)
    expect(tabular.employeeFileMismatchHint('ppt-generate-employee', 'pptx')).toContain('presentation_full.json')
    expect(tabular.employeeFileMismatchHint('unknown', 'json')).toContain('JSON')
    expect(tabular.suggestEmployeeForUploadedFile('json')).toBe('json-report-employee')
    expect(tabular.readEmployeeDisplayName('missing-id')).toBe('missing-id')

    const nested = tabular.normalizeEmployeeExecuteEnvelope({
      result: {
        outputs: [{ ok: true, output: { ok: true, paragraph_count: 2, warnings: ['w1'] } }],
        outputDownloads: [{ jobId: 'j1', filename: 'document_full.json' }],
        llm_context_text: 'inner',
        ok: true,
      },
      output_downloads: [{ job_id: 'j1', filename: 'document_full.json' }],
    })
    expect(nested.output_downloads).toHaveLength(2)
    expect(tabular.extractDirectPythonPayload(nested)?.paragraph_count).toBe(2)

    const documentJson = JSON.stringify({ metadata: { title: 'Doc' }, paragraphs: ['a'], tables: [] })
    expect(tabular.extractDocumentFullJsonText({ llm_context_text: `### document_full.json\n${documentJson}\n### next` })).toBe(documentJson)
    expect(tabular.extractDocumentFullJsonText({ result: { document_full: { paragraphs: ['a'] } } })).toContain('paragraphs')

    const presentationJson = JSON.stringify({ slides: [{ title: 'S' }] })
    expect(tabular.extractPresentationFullJsonText({ llm_context_text: presentationJson })).toBe(presentationJson)
    expect(tabular.extractPresentationFullJsonText({ result: { payload: { presentation_full: { slides: [] } } } })).toContain('slides')

    expect(tabular.extractWordReadStats({ outputs: [{ output: { items: [{ stats: { paragraph_count: 3, table_count: 1 } }] } }] })).toEqual({
      paragraphCount: 3,
      tableCount: 1,
      title: undefined,
    })

    const failed = tabular.extractEmployeeExecuteDiagnostics({
      ok: false,
      outputs: [{ ok: false, error: 'handler failed', output: { ok: false, warnings: ['warn'] } }],
    })
    expect(failed).toMatchObject({ success: false, error: 'handler failed', warnings: ['warn'] })

    const downloads = tabular.parseEmployeeOutputDownloads({
      output_downloads: [{ job_id: 'job', files: ['a.txt', { filename: 'b.txt' }] }],
      result: { downloads: [{ jobId: 'job', filename: 'presentation_full.json' }] },
    })
    expect(downloads.map((d) => d.filename)).toEqual(['a.txt', 'b.txt', 'presentation_full.json'])
    expect(tabular.pickDocumentFullJsonDownload([{ jobId: 'j', filename: 'x/document_full.json' }])).toBeTruthy()
    expect(tabular.pickPresentationFullJsonDownload(downloads)?.filename).toBe('presentation_full.json')
    expect(tabular.pickQuantitativeReportDownload([{ jobId: 'j', filename: 'quantitative_report.html' }])).toBeTruthy()

    const text = tabular.extractEmployeeReadTextForLlm({ outputs: [{ output: { rows: [{ a: 1 }] } }] })
    expect(text).toContain('"rows"')

    const summary = tabular.formatEmployeeReadResultSummary('word-full-read-employee', 'a.docx', {
      llm_context_text: documentJson,
      output_downloads: [{ job_id: 'j1', filename: 'document_full.json' }],
    })
    expect(summary.text).toContain('考试报告')
    expect(summary.downloads).toHaveLength(1)

    const jsonSummary = tabular.formatEmployeeReadResultSummary('json-report-employee', 'document_full.json', {
      meta: { source_title: 'Doc', paragraph_count: 2, table_count: 1 },
      output_downloads: [{ job_id: 'j2', filename: 'quantitative_report.html' }],
    })
    expect(jsonSummary.text).toContain('HTML 量化报告已生成')
  })

  it('runs read and generate phases including mismatch, error, download fallback, and template paths', async () => {
    const {
      pickGenerateFormat,
      runOfficeGeneratePhase,
      runOfficeReadPhase,
    } = await import('./utils/officeEmployeeRunner')

    const goodDoc = new File(['doc'], 'source.docx')
    const badPdf = new File(['pdf'], 'bad.pdf')
    const progress = vi.fn()
    mockApi.employeeExecuteFile
      .mockResolvedValueOnce({
        llm_context_text: '解析正文',
        output_downloads: [{ job_id: 'j1', filename: 'document_full.json' }],
      })
      .mockRejectedValueOnce(new Error('reader down'))

    const read = await runOfficeReadPhase({
      files: [
        { file: goodDoc, name: 'source.docx' },
        { file: badPdf, name: 'bad.pdf', readEmployeeId: 'word-full-read-employee' },
        { file: new File(['x'], 'none.xyz'), name: 'none.xyz' },
        { file: new File(['x'], 'err.docx'), name: 'err.docx' },
      ],
      userText: '总结',
      onProgress: progress,
      resolveReadEmployeeId: (item) => item.readEmployeeId || (item.name.endsWith('.xyz') ? null : 'word-full-read-employee'),
    })

    expect(read.inlineFiles[0].text).toBe('解析正文')
    expect(read.downloads).toHaveLength(1)
    expect(read.readErrors).toEqual(expect.arrayContaining([
      expect.stringContaining('当前员工不接受 .pdf'),
      expect.stringContaining('未匹配读取员工'),
      expect.stringContaining('reader down'),
    ]))
    expect(progress).toHaveBeenCalled()

    mockApi.employeeExecuteFile.mockResolvedValueOnce({
      output_downloads: [{ job_id: 'gen', filename: 'generated.docx' }],
    })
    const generated = await runOfficeGeneratePhase({
      format: 'word',
      userText: '生成文档',
      readResults: [{
        name: 'source.docx',
        employeeId: 'word-full-read-employee',
        result: { document_full: { paragraphs: ['a'] } },
      }],
    })
    expect(generated.errors).toEqual([])
    expect(generated.downloads[0].filename).toBe('generated.docx')

    mockApi.employeeOutputDownload.mockResolvedValueOnce(new Blob([JSON.stringify({ slides: [] })], { type: 'application/json' }))
    mockApi.employeeExecuteFile.mockResolvedValueOnce({
      output_downloads: [{ job_id: 'ppt', filename: 'generated.pptx' }],
    })
    const ppt = await runOfficeGeneratePhase({
      format: 'ppt',
      userText: '增强 PPT',
      readResults: [{
        name: 'deck.pptx',
        employeeId: 'ppt-full-read-employee',
        result: { output_downloads: [{ job_id: 'read', filename: 'presentation_full.json' }] },
      }],
      extraAttachmentFiles: [new File(['template'], 'template.pptx')],
    })
    expect(ppt.downloads[0].filename).toBe('generated.pptx')

    const missing = await runOfficeGeneratePhase({ format: 'excel', userText: '', readResults: [] })
    expect(missing.errors[0]).toContain('未能得到')

    mockApi.employeeExecuteFile.mockRejectedValueOnce(new Error('generate down'))
    const failed = await runOfficeGeneratePhase({
      format: 'word',
      userText: '生成',
      readResults: [{ name: 'source.docx', employeeId: 'word-full-read-employee', result: { document_full: { paragraphs: [] } } }],
    })
    expect(failed.errors).toEqual(['generate down'])

    expect(pickGenerateFormat('请制作讲义', ['deck.pptx'])).toBe('word')
    expect(pickGenerateFormat('生成 word 文档', [])).toBe('word')
  })

  it('covers runner empty reads, generated-input fallbacks, diagnostics, and non-Error failures', async () => {
    const {
      runOfficeGeneratePhase,
      runOfficeReadPhase,
    } = await import('./utils/officeEmployeeRunner')

    mockApi.employeeExecuteFile
      .mockResolvedValueOnce(null)
      .mockRejectedValueOnce('reader string failed')
    const read = await runOfficeReadPhase({
      files: [
        { file: new File(['empty'], 'empty.docx'), name: 'empty.docx' },
        { file: new File(['bad'], 'bad.docx'), name: 'bad.docx' },
      ],
      resolveReadEmployeeId: () => 'word-full-read-employee',
    })
    expect(mockApi.employeeExecuteFile.mock.calls[0][2]).toEqual({
      task: '全量读取',
      inputData: {},
    })
    expect(read.readErrors).toEqual(expect.arrayContaining([
      expect.stringContaining('读取员工未返回可用正文'),
      expect.stringContaining('reader string failed'),
    ]))
    expect(read.readSummary).toContain('empty.docx')

    mockApi.employeeOutputDownload.mockRejectedValue(new Error('download missing'))
    const missingFromDownload = await runOfficeGeneratePhase({
      format: 'ppt',
      readResults: [{
        name: 'deck.pptx',
        employeeId: 'ppt-full-read-employee',
        result: { output_downloads: [{ job_id: 'read', filename: 'presentation_full.json' }] },
      }],
    })
    expect(missingFromDownload.errors[0]).toContain('未能得到')

    const missingWithoutDownload = await runOfficeGeneratePhase({
      format: 'word',
      readResults: [{
        name: 'source.docx',
        employeeId: 'word-full-read-employee',
        result: {},
      }],
    })
    expect(missingWithoutDownload.errors[0]).toContain('未能得到')
    mockApi.employeeOutputDownload.mockReset()

    mockApi.employeeExecuteFile.mockResolvedValueOnce({})
    const textGenerated = await runOfficeGeneratePhase({
      format: 'word',
      userText: '请生成一份周报',
      readResults: [],
    })
    expect(textGenerated.summary).toContain('文字描述构建生成输入')
    expect(textGenerated.summary).toContain('若未见下载按钮')

    mockApi.employeeExecuteFile.mockResolvedValueOnce({
      ok: false,
      error: 'generate diagnostic failed',
    })
    const diagnosticFailed = await runOfficeGeneratePhase({
      format: 'word',
      userText: '生成',
      readResults: [{
        name: 'source.docx',
        employeeId: 'word-full-read-employee',
        result: { document_full: { paragraphs: ['a'] } },
      }],
    })
    expect(diagnosticFailed.errors).toContain('generate diagnostic failed')

    mockApi.employeeExecuteFile.mockResolvedValueOnce({
      output_downloads: [
        { job_id: 'gen', filename: 'report.docx', label: '报告.docx' },
        { job_id: 'gen', filename: 'appendix.docx' },
      ],
    })
    const withDownloads = await runOfficeGeneratePhase({
      format: 'word',
      userText: '生成',
      readResults: [{
        name: 'source.docx',
        employeeId: 'word-full-read-employee',
        result: { document_full: { paragraphs: ['a'] } },
      }],
    })
    expect(withDownloads.summary).toContain('报告.docx、appendix.docx')

    mockApi.employeeExecuteFile.mockRejectedValueOnce('plain generate failed')
    const stringFailed = await runOfficeGeneratePhase({
      format: 'word',
      readResults: [{
        name: 'source.docx',
        employeeId: 'word-full-read-employee',
        result: { document_full: { paragraphs: ['a'] } },
      }],
    })
    expect(stringFailed.errors).toEqual(['plain generate failed'])

    mockApi.employeeExecuteFile.mockResolvedValueOnce({
      output_downloads: [{ job_id: 'gen', filename: 'from-json.docx' }],
    })
    const fromJson = await runOfficeGeneratePhase({
      format: 'word',
      userText: '生成',
      readResults: [],
      extraAttachmentFiles: [
        new File([JSON.stringify({ paragraphs: ['json'] })], 'document_full.json', { type: 'application/json' }),
      ],
    })
    expect(fromJson.summary).toContain('结构化 JSON')
  })

  it('covers orchestration step helpers', async () => {
    const orch = await import('./utils/orchestrationSteps')
    expect(orch.isTerminalStepStatus('done')).toBe(true)
    expect(orch.isTerminalStepStatus('running')).toBe(false)
    expect(orch.resolveOrchStepId({ label: '生成产物' })).toBe('generate')
    expect(orch.resolveOrchStepId({ id: 'unknown-id', label: 'X' })).toBe('unknown-id')
    expect(orch.orchStepEmployee({ id: 'complete' })).toBe('完成')
    expect(orch.orchStepColor({ id: 'missing', label: 'Missing' })).toBe('#818cf8')
    expect(orch.computeOrchProgress([{ status: 'done' }, { status: 'running' }])).toEqual({ total: 2, done: 1, percent: 72.5 })
    expect(orch.computeOrchProgress(null)).toEqual({ total: 0, done: 0, percent: 0 })
    expect(orch.mergeOrchStepsMonotonic(
      [{ id: 'a', status: 'done', started_at: 'old' }],
      [{ id: 'a', status: 'pending', started_at: 'new' }],
    )).toEqual([{ id: 'a', status: 'done', started_at: 'old' }])
    expect(orch.mergeOrchStepsMonotonic(null, [{ id: 'b', status: 'pending' }])).toEqual([{ id: 'b', status: 'pending' }])
    expect(orch.stepMessageSummary(null)).toBe('')
    expect(orch.stepMessageSummary(' hi ')).toBe('hi')
    expect(orch.stepMessageSummary({ summary: ' ok ' })).toBe('ok')
  })
})
