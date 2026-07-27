import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { etlApiMock } = vi.hoisted(() => ({
  etlApiMock: {
    capabilities: vi.fn(),
    templates: vi.fn(),
    runs: vi.fn(),
    targetConfigs: vi.fn(),
    upload: vi.fn(),
    preview: vi.fn(),
    run: vi.fn(),
    rows: vi.fn(),
    patchDraft: vi.fn(),
    execute: vi.fn(),
    retry: vi.fn(),
    rollback: vi.fn(),
    createTemplate: vi.fn(),
    createTargetConfig: vi.fn(),
    testTarget: vi.fn(),
    exportUrl: vi.fn(),
    errorExportUrl: vi.fn(),
  },
}))

vi.mock('@/api/etl', () => ({ etlApi: etlApiMock }))

import EtlCenterView from './EtlCenterView.vue'

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/business-docking', component: EtlCenterView }],
  })
  await router.push('/business-docking')
  await router.isReady()
  const wrapper = mount(EtlCenterView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

function folderFile(name: string, relativePath: string) {
  const file = new File(['data'], name, { type: 'text/csv', lastModified: 123 })
  Object.defineProperty(file, 'webkitRelativePath', { value: relativePath })
  return file
}

function queuedRun(id: string, fileName: string) {
  return {
    id,
    upload_id: `upload-${id}`,
    file_name: fileName,
    file_sha256: id,
    target_type: 'customer_products',
    status: 'queued',
    stage: 'queued',
    progress: 0,
    total_rows: 0,
    processed_rows: 0,
    summary: { new: 0, update: 0, skip: 0, error: 0, executed: 0 },
    details: {},
    source_features: {},
    draft: {},
    receipt: {},
    reversible: true,
  }
}

describe('EtlCenterView folder workflow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    etlApiMock.capabilities.mockResolvedValue({
      enabled: true,
      limits: { max_file_bytes: 50 * 1024 * 1024, max_rows: 100_000 },
      inputs: { structured: [], ocr: [], knowledge_only: [], folder_upload: true },
      transforms: [],
      targets: [
        {
          type: 'customer_products',
          label: '客户及产品',
          fields: [],
          required_fields: [],
          default_match_keys: [],
          supported_actions: ['new', 'skip'],
          reversible: true,
        },
      ],
      execution_policy: {},
    })
    etlApiMock.templates.mockResolvedValue([])
    etlApiMock.runs.mockResolvedValue([])
    etlApiMock.targetConfigs.mockResolvedValue([])
  })

  it('shows separate file and whole-folder pickers', async () => {
    const wrapper = await mountView()

    expect(wrapper.text()).toContain('选择整个文件夹')
    expect(wrapper.find('input[type="file"][multiple]').exists()).toBe(true)
    expect(wrapper.find('input[type="file"][webkitdirectory]').exists()).toBe(true)
  })

  it('shows folder name, file count, relative paths, and batch action', async () => {
    const wrapper = await mountView()
    const input = wrapper.find('input[type="file"][webkitdirectory]')
    const files = [
      folderFile('customers.csv', '华东批次/客户/customers.csv'),
      folderFile('products.csv', '华东批次/产品/products.csv'),
    ]
    Object.defineProperty(input.element, 'files', { value: files })
    await input.trigger('change')

    expect(wrapper.text()).toContain('华东批次 · 2 个可处理文件')
    expect(wrapper.text()).toContain('华东批次/客户/customers.csv')
    expect(wrapper.text()).toContain('华东批次/产品/products.csv')
    expect(wrapper.text()).toContain('批量上传并创建 2 个预演')
    wrapper.unmount()
  })

  it('uploads every folder file with one batch id and its own relative path', async () => {
    etlApiMock.upload.mockImplementation(async (file: File) => ({
      upload_id: `upload-${file.name}`,
      file_name: file.name,
      suffix: '.csv',
      size_bytes: file.size,
      sha256: file.name,
    }))
    etlApiMock.preview.mockImplementation(async ({ upload_id }: { upload_id: string }) => (
      queuedRun(`run-${upload_id}`, upload_id)
    ))
    const wrapper = await mountView()
    const input = wrapper.find('input[type="file"][webkitdirectory]')
    const files = [
      folderFile('customers.csv', '华东批次/客户/customers.csv'),
      folderFile('products.csv', '华东批次/产品/products.csv'),
    ]
    Object.defineProperty(input.element, 'files', { value: files })
    await input.trigger('change')
    const start = wrapper.findAll('button').find((button) => (
      button.text().includes('批量上传并创建 2 个预演')
    ))
    await start?.trigger('click')
    await flushPromises()

    expect(etlApiMock.upload).toHaveBeenCalledTimes(2)
    const options = etlApiMock.upload.mock.calls.map((call) => call[1])
    expect(new Set(options.map((item) => item.batchId)).size).toBe(1)
    expect(options.map((item) => item.relativePath)).toEqual([
      '华东批次/客户/customers.csv',
      '华东批次/产品/products.csv',
    ])
    expect(etlApiMock.preview).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})
