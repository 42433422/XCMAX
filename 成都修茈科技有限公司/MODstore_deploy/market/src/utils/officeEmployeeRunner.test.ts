import { describe, it, expect, beforeEach, vi } from 'vitest'

const { employeeExecuteFileMock } = vi.hoisted(() => ({
  employeeExecuteFileMock: vi.fn(),
}))

vi.mock('../api', () => ({
  api: {
    employeeExecuteFile: employeeExecuteFileMock,
    employeeOutputDownload: vi.fn(),
  },
}))

import {
  pickGenerateFormat,
  runOfficeReadPhase,
  type OfficeReadFileItem,
} from './officeEmployeeRunner'
import type { OfficeFormat } from './officeEmployeeOrchestration'

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
