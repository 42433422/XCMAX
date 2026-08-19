import { describe, it, expect, beforeEach, vi } from 'vitest'

const { employeeExecuteFileMock, employeeOutputDownloadMock } = vi.hoisted(() => ({
  employeeExecuteFileMock: vi.fn(),
  employeeOutputDownloadMock: vi.fn(),
}))

vi.mock('../api', () => ({
  api: {
    employeeExecuteFile: employeeExecuteFileMock,
    employeeOutputDownload: employeeOutputDownloadMock,
  },
}))

import {
  pickGenerateFormat,
  runOfficeGeneratePhase,
  runOfficeReadPhase,
  type OfficeReadFileItem,
} from './officeEmployeeRunner'

describe('pickGenerateFormat', () => {
  it('returns word for empty userText and empty attachments', () => {
    expect(pickGenerateFormat('', [])).toBe('word')
  })

  it('returns ppt when attachment is pptx and no generate intent', () => {
    expect(pickGenerateFormat('读取这个文件', ['report.pptx'])).toBe('ppt')
  })

  it('returns word when attachment is docx', () => {
    expect(pickGenerateFormat('', ['doc.docx'])).toBe('word')
  })

  it('returns excel when attachment is xlsx', () => {
    expect(pickGenerateFormat('', ['data.xlsx'])).toBe('excel')
  })

  it('returns ppt when userText contains 生成PPT intent', () => {
    const result = pickGenerateFormat('生成一份PPT', [])
    expect(['ppt', 'word']).toContain(result)
  })

  it('prefers pptx attachment format when enhance attached intent', () => {
    const result = pickGenerateFormat('美化', ['slides.pptx'])
    expect(result).toBe('ppt')
  })

  it('returns csv when attachment is csv', () => {
    expect(pickGenerateFormat('', ['export.csv'])).toBe('csv')
  })

  it('returns pdf when attachment is pdf', () => {
    expect(pickGenerateFormat('', ['doc.pdf'])).toBe('pdf')
  })

  it('handles multiple attachments with mixed formats', () => {
    const result = pickGenerateFormat('', ['a.docx', 'b.xlsx'])
    expect(['word', 'excel']).toContain(result)
  })

  it('handles null-like inputs gracefully', () => {
    expect(pickGenerateFormat('', [])).toBe('word')
  })
})

describe('runOfficeReadPhase', () => {
  beforeEach(() => {
    employeeExecuteFileMock.mockReset()
  })

  it('returns empty result for empty files array', async () => {
    const result = await runOfficeReadPhase({
      files: [],
      resolveReadEmployeeId: () => null,
    })
    expect(result.inlineFiles).toEqual([])
    expect(result.downloads).toEqual([])
    expect(result.readErrors).toEqual([])
    expect(result.readSummary).toBe('')
    expect(result.rawResults).toEqual([])
  })

  it('reports error when no employee matches', async () => {
    const item: OfficeReadFileItem = {
      file: new File([''], 'test.docx'),
      name: 'test.docx',
    }
    const result = await runOfficeReadPhase({
      files: [item],
      resolveReadEmployeeId: () => null,
    })
    expect(result.readErrors).toHaveLength(1)
    expect(result.readErrors[0]).toContain('未匹配读取员工')
    expect(employeeExecuteFileMock).not.toHaveBeenCalled()
  })

  it('reports error when file extension is not accepted', async () => {
    const item: OfficeReadFileItem = {
      file: new File([''], 'test.xyz'),
      name: 'test.xyz',
    }
    const result = await runOfficeReadPhase({
      files: [item],
      resolveReadEmployeeId: () => 'word-full-read-employee',
    })
    expect(result.readErrors).toHaveLength(1)
    expect(employeeExecuteFileMock).not.toHaveBeenCalled()
  })

  it('calls onProgress during read', async () => {
    employeeExecuteFileMock.mockResolvedValueOnce({
      read_text: 'extracted content',
      downloads: [],
    })
    const onProgress = vi.fn()
    const item: OfficeReadFileItem = {
      file: new File(['content'], 'test.docx'),
      name: 'test.docx',
    }
    await runOfficeReadPhase({
      files: [item],
      resolveReadEmployeeId: () => 'word-full-read-employee',
      onProgress,
    })
    expect(onProgress).toHaveBeenCalled()
  })

  it('handles api errors and records them in readErrors', async () => {
    employeeExecuteFileMock.mockRejectedValueOnce(new Error('api down'))
    const item: OfficeReadFileItem = {
      file: new File(['content'], 'test.docx'),
      name: 'test.docx',
    }
    const result = await runOfficeReadPhase({
      files: [item],
      resolveReadEmployeeId: () => 'word-full-read-employee',
    })
    expect(result.readErrors).toHaveLength(1)
    expect(result.readErrors[0]).toContain('api down')
  })

  it('uses JSON fallback when employee returns minimal response', async () => {
    employeeExecuteFileMock.mockResolvedValueOnce({
      llm_context_text: '',
      outputs: [],
    })
    const item: OfficeReadFileItem = {
      file: new File(['content'], 'test.docx'),
      name: 'test.docx',
    }
    const result = await runOfficeReadPhase({
      files: [item],
      resolveReadEmployeeId: () => 'word-full-read-employee',
    })
    expect(result.readErrors).toEqual([])
    expect(result.inlineFiles).toHaveLength(1)
    expect(result.inlineFiles[0].text).toContain('llm_context_text')
    expect(result.readSummary).not.toBe('')
  })

  it('passes userText to employee execute when provided', async () => {
    employeeExecuteFileMock.mockResolvedValueOnce({
      read_text: 'content',
      downloads: [],
    })
    const item: OfficeReadFileItem = {
      file: new File(['content'], 'test.docx'),
      name: 'test.docx',
    }
    await runOfficeReadPhase({
      files: [item],
      userText: 'summarize this',
      resolveReadEmployeeId: () => 'word-full-read-employee',
    })
    expect(employeeExecuteFileMock).toHaveBeenCalledWith(
      'word-full-read-employee',
      expect.any(File),
      expect.objectContaining({
        task: '全量读取并供后续问答',
        inputData: { user_query: 'summarize this' },
      }),
    )
  })

  it('collects inline files and downloads on success', async () => {
    employeeExecuteFileMock.mockResolvedValueOnce({
      llm_context_text: 'extracted text content for LLM context',
      output_downloads: [{ jobId: 'j1', filename: 'out.xlsx', label: 'Output' }],
    })
    const item: OfficeReadFileItem = {
      file: new File(['content'], 'test.docx'),
      name: 'test.docx',
    }
    const result = await runOfficeReadPhase({
      files: [item],
      resolveReadEmployeeId: () => 'word-full-read-employee',
    })
    expect(result.inlineFiles).toHaveLength(1)
    expect(result.inlineFiles[0].text).toBe('extracted text content for LLM context')
    expect(result.rawResults).toHaveLength(1)
  })
})

describe('runOfficeGeneratePhase', () => {
  beforeEach(() => {
    employeeExecuteFileMock.mockReset()
    employeeOutputDownloadMock.mockReset()
  })

  it('returns an actionable error when neither source data nor text is supplied', async () => {
    const result = await runOfficeGeneratePhase({ format: 'word' })
    expect(result.downloads).toEqual([])
    expect(result.errors[0]).toContain('未能得到')
    expect(employeeExecuteFileMock).not.toHaveBeenCalled()
  })

  it('builds structured input from text and returns generated downloads', async () => {
    employeeExecuteFileMock.mockResolvedValueOnce({
      success: true,
      output_downloads: [{ job_id: 'job-word', filename: 'proposal.docx', label: 'Proposal' }],
    })
    const result = await runOfficeGeneratePhase({
      format: 'word',
      userText: '生成一份三段式销售提案，包含背景、方案和下一步',
    })
    expect(result.errors).toEqual([])
    expect(result.downloads[0].filename).toBe('proposal.docx')
    expect(result.summary).toContain('文字描述')
    expect(employeeExecuteFileMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ name: 'generate_input.json' }),
      expect.objectContaining({ timeoutMs: 180_000 }),
    )
  })

  it('reuses presentation JSON and template metadata for PPT generation', async () => {
    employeeExecuteFileMock.mockResolvedValueOnce({
      success: true,
      output_downloads: [{ job_id: 'job-ppt', filename: 'output.pptx', label: 'Slides' }],
    })
    const template = new File(['template'], 'brand-template.pptx')
    const result = await runOfficeGeneratePhase({
      format: 'ppt',
      userText: '增强这份演示',
      templateFile: template,
      readResults: [{
        name: 'source.pptx',
        employeeId: 'ppt-full-read-employee',
        result: { llm_context_text: JSON.stringify({ slides: [{ title: 'Opening' }] }) },
      }],
    })
    expect(result.downloads[0].filename).toBe('output.pptx')
    expect(employeeExecuteFileMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ name: 'presentation_full.json' }),
      expect.objectContaining({
        template,
        inputData: expect.objectContaining({
          has_template: true,
          source_filename: 'source.pptx',
        }),
      }),
    )
  })

  it('downloads JSON fallbacks and reports execution or transport failures', async () => {
    employeeOutputDownloadMock.mockResolvedValueOnce(new Blob(['{"paragraphs":[]}']))
    employeeExecuteFileMock
      .mockResolvedValueOnce({ ok: false, error: 'generator rejected input' })
      .mockRejectedValueOnce(new Error('generator offline'))
    const readResults = [{
      name: 'source.docx',
      employeeId: 'word-full-read-employee',
      result: {
        output_downloads: [{
          job_id: 'job-json', filename: 'document_full.json', label: 'Document JSON',
        }],
      },
    }]
    const rejected = await runOfficeGeneratePhase({ format: 'word', readResults })
    expect(rejected.errors).toContain('generator rejected input')
    const offline = await runOfficeGeneratePhase({
      format: 'word', userText: 'Generate from this description',
    })
    expect(offline.errors).toEqual(['generator offline'])
  })
})
