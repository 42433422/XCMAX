import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import EmployeeExamView from './EmployeeExamView.vue'
import { ApiError } from '../infrastructure/http/client'

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

  it('shows employee loading errors and keeps v1/json fallback options', async () => {
    vi.mocked(api.listEmployees).mockRejectedValue(new Error('employee api down'))
    vi.mocked(api.listV1Packages).mockResolvedValue({
      packages: [{ id: 'excel-full-read-employee', name: 'Excel 读取员' }],
    })

    const wrapper = mount(EmployeeExamView)
    await flushPromises()

    expect(wrapper.text()).toContain('加载员工列表失败：employee api down')
    const options = wrapper.findAll('option').map((o) => o.attributes('value'))
    expect(options).toContain('excel-full-read-employee')
    expect(options).toContain('json-report-employee')
  })

  it('auto-switches employee for mismatched xlsx uploads and clears selected files', async () => {
    vi.mocked(api.listEmployees).mockResolvedValue([
      { id: 'word-full-read-employee', name: 'Word 读取员' },
      { id: 'excel-full-read-employee', name: 'Excel 读取员' },
      { id: 'json-report-employee', name: 'JSON 量化报告员' },
    ])
    const wrapper = mount(EmployeeExamView)
    await flushPromises()
    await wrapper.find('#exam-employee-select').setValue('word-full-read-employee')

    const file = new File(['x'.repeat(2048)], 'score.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const input = wrapper.find('.exam-file-input')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()

    expect((wrapper.find('#exam-employee-select').element as HTMLSelectElement).value).toBe('excel-full-read-employee')
    expect(wrapper.text()).toContain('2.0 KB')

    await wrapper.find('.exam-file-chip + .btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.exam-file-chip').exists()).toBe(false)
  })

  it('opens and downloads generated HTML reports', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:exam-report'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    vi.mocked(api.employeeExecuteFile).mockResolvedValue({
      employee_id: 'json-report-employee',
      output_downloads: [
        { job_id: 'j-html', filename: 'quantitative_report.html', label: 'quantitative_report.html' },
        { job_id: 'j-json', filename: 'document_full.json', label: 'document_full.json' },
      ],
      result: { outputs: [{ handler: 'direct_python', ok: true, output: { ok: true } }] },
    })
    vi.mocked(api.employeeOutputDownload).mockResolvedValue(
      new Blob(['<html><body>report</body></html>'], { type: 'text/html' }),
    )

    const wrapper = mount(EmployeeExamView)
    await flushPromises()
    await wrapper.find('#exam-employee-select').setValue('json-report-employee')
    const file = new File(['{}'], 'document_full.json', { type: 'application/json' })
    Object.defineProperty(wrapper.find('.exam-file-input').element, 'files', { value: [file], configurable: true })
    await wrapper.find('.exam-file-input').trigger('change')
    await wrapper.find('.btn-block').trigger('click')
    await flushPromises()
    await flushPromises()

    await wrapper.find('.exam-report-card-actions .btn-ghost').trigger('click')
    expect(openSpy).toHaveBeenCalledWith('blob:exam-report', '_blank', 'noopener,noreferrer')

    await wrapper.find('.exam-report-card-actions .btn-connect').trigger('click')
    await flushPromises()
    expect(api.employeeOutputDownload).toHaveBeenCalledWith('j-html', 'quantitative_report.html')
  })

  it('formats API errors for forbidden, oversized, and json mismatch cases', async () => {
    const cases = [
      [new ApiError('forbidden', 403), '无权执行该员工包'],
      [new ApiError('payload too large', 413), 'payload too large'],
      [new ApiError('文件类型不匹配', 400), '生成报告需后端支持 .json 上传'],
    ] as const

    for (const [error, expected] of cases) {
      vi.mocked(api.employeeExecuteFile).mockRejectedValueOnce(error)
      const wrapper = mount(EmployeeExamView)
      await flushPromises()
      const file = new File(['{}'], 'document_full.json', { type: 'application/json' })
      await wrapper.find('#exam-employee-select').setValue('json-report-employee')
      Object.defineProperty(wrapper.find('.exam-file-input').element, 'files', { value: [file], configurable: true })
      await wrapper.find('.exam-file-input').trigger('change')
      await wrapper.find('.btn-action').trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain(expected)
      wrapper.unmount()
    }
  })

  it('merges employee options while skipping blanks and duplicate v1 package ids', async () => {
    vi.mocked(api.listEmployees).mockResolvedValue([
      { id: '', name: 'Blank' },
      { id: 'word-full-read-employee', name: 'Word A' },
    ])
    vi.mocked(api.listV1Packages).mockResolvedValue({
      packages: [
        { id: '', name: 'Blank V1' },
        { id: 'word-full-read-employee', name: 'Word V1' },
        { id: 'ppt-full-read-employee', name: '' },
      ],
    })

    const wrapper = mount(EmployeeExamView)
    await flushPromises()

    const options = wrapper.findAll('option').map((o) => ({
      value: o.attributes('value'),
      text: o.text(),
    }))
    expect(options.filter((o) => o.value === 'word-full-read-employee')).toHaveLength(1)
    expect(options.map((o) => o.value)).toContain('ppt-full-read-employee')
    expect(options.find((o) => o.value === 'ppt-full-read-employee')?.text).toContain('ppt-full-read-employee')
  })

  it('covers drag-drop selection, mismatch without suggested employee, and plain string results', async () => {
    vi.mocked(api.listEmployees).mockResolvedValue([
      { id: 'json-report-employee', name: 'JSON 量化报告员' },
    ])
    const mismatch = mount(EmployeeExamView)
    await flushPromises()
    await mismatch.find('#exam-employee-select').setValue('json-report-employee')

    ;(mismatch.vm as any).onDrop({
      dataTransfer: { files: [new File(['doc'], 'paper.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })] },
    } as DragEvent)
    await flushPromises()
    expect(mismatch.text()).toContain('当前员工不接受 .docx')
    await mismatch.find('.btn-action').trigger('click')
    await flushPromises()
    expect(api.employeeExecuteFile).not.toHaveBeenCalled()

    vi.mocked(api.listEmployees).mockResolvedValue([
      { id: 'word-full-read-employee', name: 'Word 读取员' },
      { id: 'json-report-employee', name: 'JSON 量化报告员' },
    ])
    vi.mocked(api.employeeExecuteFile).mockResolvedValueOnce('plain execute result')
    const plain = mount(EmployeeExamView)
    await flushPromises()
    Object.defineProperty(plain.find('.exam-file-input').element, 'files', {
      value: [new File(['x'], 'plain.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })],
      configurable: true,
    })
    await plain.find('.exam-file-input').trigger('change')
    await plain.find('.btn-action').trigger('click')
    await flushPromises()
    expect((plain.vm as any).rawJsonPreview).toContain('plain execute result')
  })

  it('renders drag hover, file picker, summary, raw json, and download busy states', async () => {
    const wrapper = mount(EmployeeExamView)
    await flushPromises()

    const inputEl = wrapper.find('.exam-file-input').element as HTMLInputElement
    const clickSpy = vi.spyOn(inputEl, 'click').mockImplementation(() => undefined)
    await wrapper.find('.btn-connect.btn-sm').trigger('click')
    expect(clickSpy).toHaveBeenCalled()

    const dropzone = wrapper.find('.exam-dropzone')
    await dropzone.trigger('dragover')
    expect(dropzone.classes()).toContain('exam-dropzone--active')
    await dropzone.trigger('dragleave')
    expect(dropzone.classes()).not.toContain('exam-dropzone--active')

    const vm = wrapper.vm as any
    vm.resultSummary = '摘要一\n摘要二'
    vm.rawJsonPreview = '{"ok":true}'
    vm.downloads = [
      { jobId: 'job-html', filename: 'quantitative_report.html', label: '量化报告' },
      { jobId: 'job-text', filename: 'out.txt', label: '' },
    ]
    vm.htmlReportPreviewUrl = 'blob:report'
    vm.downloadingKey = 'job-html:quantitative_report.html'
    await flushPromises()

    expect(wrapper.find('.exam-more-summary').exists()).toBe(true)
    expect(wrapper.find('.exam-raw-pre').text()).toContain('"ok":true')
    expect(wrapper.find('.exam-report-card-actions .btn-connect').text()).toContain('…')

    vm.downloadingKey = 'job-text:out.txt'
    await flushPromises()
    expect(wrapper.findAll('.exam-more-file-btn').some((btn) => btn.text().includes('下载中'))).toBe(true)
  })

  it('covers manual report, preview, and download error branches', async () => {
    const wrapper = mount(EmployeeExamView)
    await flushPromises()
    const vm = wrapper.vm as any

    vm.openHtmlReportInNewTab()

    vi.mocked(api.employeeExecuteFile).mockResolvedValueOnce({
      employee_id: 'word-full-read-employee',
      result: {
        outputs: [{ handler: 'direct_python', ok: true, output: { ok: true, paragraph_count: 1 } }],
      },
      output_downloads: [],
    })
    Object.defineProperty(wrapper.find('.exam-file-input').element, 'files', {
      value: [new File(['x'], 'no-document-full.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })],
      configurable: true,
    })
    await wrapper.find('.exam-file-input').trigger('change')
    await wrapper.find('.btn-action').trigger('click')
    await flushPromises()
    await vm.generateReportFromRead()
    await flushPromises()
    expect(wrapper.text()).toContain('未找到 document_full.json')

    vi.mocked(api.employeeOutputDownload).mockRejectedValueOnce(new Error('download down'))
    await vm.downloadOutput({ jobId: 'job-download', filename: 'out.txt' })
    await flushPromises()
    expect(wrapper.text()).toContain('下载失败：download down')

    vi.mocked(api.employeeExecuteFile).mockResolvedValueOnce({
      employee_id: 'json-report-employee',
      output_downloads: [
        { job_id: 'j-html', filename: 'quantitative_report.html', label: 'quantitative_report.html' },
      ],
      result: { outputs: [{ handler: 'direct_python', ok: true, output: { ok: true } }] },
    })
    vi.mocked(api.employeeOutputDownload).mockRejectedValueOnce(new Error('preview down'))
    const preview = mount(EmployeeExamView)
    await flushPromises()
    await preview.find('#exam-employee-select').setValue('json-report-employee')
    Object.defineProperty(preview.find('.exam-file-input').element, 'files', {
      value: [new File(['{}'], 'document_full.json', { type: 'application/json' })],
      configurable: true,
    })
    await preview.find('.exam-file-input').trigger('change')
    await preview.find('.btn-action').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(preview.text()).toContain('预览失败：preview down')
  })

  it('covers remaining report pipeline computed and json-only branches', async () => {
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:exam-report-next'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    vi.mocked(api.employeeOutputDownload).mockResolvedValue(
      new Blob(['{"document_full":true}'], { type: 'application/json' }),
    )
    vi.mocked(api.employeeExecuteFile).mockResolvedValue({
      employee_id: 'json-report-employee',
      output_downloads: [],
      result: { outputs: [{ handler: 'direct_python', ok: true, output: { ok: true } }] },
    })

    const wrapper = mount(EmployeeExamView)
    await flushPromises()
    const vm = wrapper.vm as any

    vm.htmlReportPreviewUrl = 'blob:old-report'
    vm.revokeHtmlPreview()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:old-report')

    await wrapper.find('#exam-employee-select').setValue('json-report-employee')
    Object.defineProperty(wrapper.find('.exam-file-input').element, 'files', {
      value: [new File(['{}'], 'document_full.json', { type: 'application/json' })],
      configurable: true,
    })
    await wrapper.find('.exam-file-input').trigger('change')
    vm.downloads = [{ jobId: 'doc-job', filename: 'document_full.json', label: 'document_full.json' }]
    expect(vm.canGenerateReportFromRead).toBe(true)
    expect(vm.showManualReportButton).toBe(true)
    await vm.generateReportFromRead()
    await flushPromises()

    expect(api.employeeExecuteFile).toHaveBeenCalledWith(
      'json-report-employee',
      expect.any(File),
      expect.objectContaining({ task: '考试生成量化报告' }),
    )
    expect(wrapper.text()).toContain('未找到 quantitative_report.html')
    expect(vm.lastRunKind).toBe('json_only')
  })
})
