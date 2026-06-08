import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import EmployeeExamView from './EmployeeExamView.vue'

vi.mock('../api', () => ({
  api: {
    listEmployees: vi.fn(),
    listV1Packages: vi.fn(),
    employeeExecuteFile: vi.fn(),
    employeeOutputDownload: vi.fn(),
  },
}))

import { api } from '../api'

describe('EmployeeExamView', () => {
  beforeEach(() => {
    vi.mocked(api.employeeExecuteFile).mockReset()
    vi.mocked(api.employeeOutputDownload).mockReset()
    vi.mocked(api.listEmployees).mockResolvedValue([
      { id: 'word-full-read-employee', name: 'Word 读取员' },
      { id: 'json-report-employee', name: 'JSON 量化报告员' },
    ])
    vi.mocked(api.listV1Packages).mockResolvedValue({ packages: [] })
    vi.mocked(api.employeeExecuteFile).mockResolvedValue({
      ok: true,
      llm_context_text: '段落一\n段落二',
      output_downloads: [],
    })
  })

  it('disables run button without a file', async () => {
    const wrapper = mount(EmployeeExamView)
    await flushPromises()
    const runBtn = wrapper.find('.btn-action')
    expect(runBtn.attributes('disabled')).toBeDefined()
  })

  it('runs execute-file and shows summary', async () => {
    const wrapper = mount(EmployeeExamView)
    await flushPromises()

    const file = new File(['x'], 'sample.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    })
    const input = wrapper.find('.exam-file-input')
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    await flushPromises()

    const runBtn = wrapper.find('.btn-action')
    expect(runBtn.attributes('disabled')).toBeUndefined()
    await runBtn.trigger('click')
    await flushPromises()

    expect(api.employeeExecuteFile).toHaveBeenCalledWith(
      'word-full-read-employee',
      expect.any(File),
      expect.objectContaining({ task: '考试试跑' }),
    )
    expect(wrapper.find('.exam-pipeline').exists()).toBe(true)
    expect(wrapper.text()).toContain('Word')
    expect(runBtn.text()).toContain('试跑并自动生成报告')
  })

  it('auto-generates report after word read with document_full.json', async () => {
    vi.mocked(api.employeeExecuteFile)
      .mockResolvedValueOnce({
        employee_id: 'word-full-read-employee',
        output_downloads: [{ job_id: 'j1', filename: 'document_full.json', label: 'document_full.json' }],
        result: {
          outputs: [{ handler: 'direct_python', ok: true, output: { ok: true, paragraph_count: 5 } }],
        },
      })
      .mockResolvedValueOnce({
        employee_id: 'json-report-employee',
        output_downloads: [
          { job_id: 'j2', filename: 'quantitative_report.html', label: 'quantitative_report.html' },
        ],
        result: {
          outputs: [
            {
              handler: 'direct_python',
              ok: true,
              output: { ok: true, report_html_path: 'outputs/quantitative_report.html' },
            },
          ],
        },
      })
    vi.mocked(api.employeeOutputDownload).mockImplementation(async (_job, filename) => {
      if (String(filename).includes('.html')) {
        return new Blob(['<html><body>report</body></html>'], { type: 'text/html' })
      }
      return new Blob(['{}'], { type: 'application/json' })
    })

    const wrapper = mount(EmployeeExamView)
    await flushPromises()

    const file = new File(['x'], '3.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    })
    const input = wrapper.find('.exam-file-input')
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    const runBtn = wrapper.find('.btn-block')
    await runBtn.trigger('click')
    await flushPromises()
    await flushPromises()

    expect(api.employeeExecuteFile).toHaveBeenCalledTimes(2)
    expect(api.employeeExecuteFile).toHaveBeenLastCalledWith(
      'json-report-employee',
      expect.any(File),
      expect.objectContaining({
        task: '考试生成量化报告',
        inputData: expect.objectContaining({ skip_llm: true }),
      }),
    )
    await flushPromises()
    expect(wrapper.find('.exam-report-card').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('```json')
    expect(wrapper.find('.exam-done-chip').exists()).toBe(true)
    expect(wrapper.text()).toContain('流程已完成')
    expect(wrapper.text()).toContain('3.docx')
    expect(wrapper.text()).toContain('Word 读取 + 报告生成')
    expect((wrapper.find('#exam-employee-select').element as HTMLSelectElement).value).toBe(
      'word-full-read-employee',
    )
    expect(wrapper.text()).not.toContain('更适合')
  })

  it('uses json-only pipeline when uploading json to json-report employee', async () => {
    vi.mocked(api.employeeExecuteFile).mockResolvedValue({
      employee_id: 'json-report-employee',
      output_downloads: [
        { job_id: 'j1', filename: 'quantitative_report.html', label: 'quantitative_report.html' },
      ],
      result: { outputs: [{ handler: 'direct_python', ok: true, output: { ok: true } }] },
    })
    vi.mocked(api.employeeOutputDownload).mockResolvedValue(
      new Blob(['<html><body>x</body></html>'], { type: 'text/html' }),
    )

    const wrapper = mount(EmployeeExamView)
    await flushPromises()
    await wrapper.find('#exam-employee-select').setValue('json-report-employee')

    const file = new File(['{}'], 'document_full.json', { type: 'application/json' })
    Object.defineProperty(wrapper.find('.exam-file-input').element, 'files', { value: [file] })
    await wrapper.find('.exam-file-input').trigger('change')
    await wrapper.find('.btn-block').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(api.employeeExecuteFile).toHaveBeenCalledTimes(1)
    expect(api.employeeExecuteFile).toHaveBeenCalledWith(
      'json-report-employee',
      expect.any(File),
      expect.objectContaining({ task: '考试生成量化报告' }),
    )
    expect(wrapper.text()).toContain('document_full.json')
    expect(wrapper.text()).not.toContain('Word 读取 + 报告生成')
  })

  it('shows failure state when execute returns ok false', async () => {
    vi.mocked(api.employeeExecuteFile).mockResolvedValue({
      outputs: [
        {
          handler: 'direct_python',
          ok: false,
          output: { ok: false, error: '无法解析旧版 .doc：请安装 LibreOffice' },
        },
      ],
    })
    const wrapper = mount(EmployeeExamView)
    await flushPromises()
    const file = new File(['x'], '3.doc', { type: 'application/msword' })
    Object.defineProperty(wrapper.find('.exam-file-input').element, 'files', { value: [file] })
    await wrapper.find('.exam-file-input').trigger('change')
    await wrapper.find('.btn-action').trigger('click')
    await flushPromises()
    expect(wrapper.find('.exam-failure').exists()).toBe(true)
    expect(wrapper.text()).toContain('试跑失败')
    expect(wrapper.text()).toContain('LibreOffice')
  })
})
