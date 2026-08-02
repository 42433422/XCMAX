import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PersyImportDrawer from './PersyImportDrawer.vue'

const mocks = vi.hoisted(() => ({
  uploadDocument: vi.fn(),
  ingestDocument: vi.fn(),
}))

vi.mock('@/api/knowledgeBase', () => ({
  knowledgeBaseApi: mocks,
}))

function mountDrawer() {
  return mount(PersyImportDrawer, {
    props: {
      datasetId: 'persy-knowledge',
      datasetIdInput: 'persy-knowledge',
      sourcePlaceholder: '资料名称',
      textPlaceholder: '资料内容',
    },
  })
}

function expose(wrapper: ReturnType<typeof mountDrawer>) {
  return wrapper.vm as unknown as { open: (mode: 'file' | 'text') => void }
}

describe('PersyImportDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.uploadDocument.mockResolvedValue({ success: true, chunk_count: 3 })
    mocks.ingestDocument.mockResolvedValue({ success: true, document: { chunk_count: 2 } })
  })

  it('imports text, updates the dataset model, and closes after success', async () => {
    const wrapper = mountDrawer()
    expose(wrapper).open('text')
    await wrapper.vm.$nextTick()

    await wrapper.get('input[aria-label="数据集"]').setValue('tenant-space')
    expect(wrapper.emitted('update:datasetIdInput')).toEqual([['tenant-space']])

    await wrapper.get('#persy-text').setValue('续约需要财务审批。')
    await wrapper.get('.drawer-submit').trigger('click')
    await flushPromises()

    expect(mocks.ingestDocument).toHaveBeenCalledWith({
      datasetId: 'persy-knowledge',
      source: 'Persy 系统资料',
      text: '续约需要财务审批。',
      metadata: {
        scope: 'persy',
        entrypoint: 'persy_knowledge_view',
      },
    })
    expect(wrapper.emitted('clearMessage')).toHaveLength(1)
    expect(wrapper.emitted('ingested')).toEqual([['已形成 2 个知识节点']])
    expect(wrapper.find('.import-drawer').exists()).toBe(false)
  })

  it('validates file selection and uploads a supported document', async () => {
    const wrapper = mountDrawer()
    expose(wrapper).open('file')
    await wrapper.vm.$nextTick()

    await wrapper.get('.drawer-submit').trigger('click')
    expect(wrapper.get('[role="alert"]').text()).toContain('请选择资料文件')

    const input = wrapper.get('input[type="file"]')
    const invalid = new File(['bad'], 'payload.exe', { type: 'application/octet-stream' })
    Object.defineProperty(input.element, 'files', { configurable: true, value: [invalid] })
    await input.trigger('change')
    expect(wrapper.get('[role="alert"]').text()).toContain('不支持的资料类型')

    const valid = new File(['hello'], 'handbook.pdf', { type: 'application/pdf' })
    Object.defineProperty(input.element, 'files', { configurable: true, value: [valid] })
    await input.trigger('change')
    expect(wrapper.text()).toContain('handbook.pdf')

    await wrapper.get('.drawer-submit').trigger('click')
    await flushPromises()

    expect(mocks.uploadDocument).toHaveBeenCalledWith({
      datasetId: 'persy-knowledge',
      source: 'handbook.pdf',
      file: valid,
    })
    expect(wrapper.emitted('ingested')).toEqual([['已形成 3 个知识节点']])
  })

  it('handles picker, drop, oversized files, clearing, and API errors', async () => {
    const wrapper = mountDrawer()
    expose(wrapper).open('file')
    await wrapper.vm.$nextTick()

    const input = wrapper.get('input[type="file"]')
    const click = vi.spyOn(input.element as HTMLInputElement, 'click')
    await wrapper.get('.drop-zone').trigger('click')
    expect(click).toHaveBeenCalled()

    const oversized = new File(['x'], 'archive.pdf', { type: 'application/pdf' })
    Object.defineProperty(oversized, 'size', { configurable: true, value: 26 * 1024 * 1024 })
    await wrapper.get('.drop-zone').trigger('drop', {
      dataTransfer: { files: [oversized] },
    })
    expect(wrapper.get('[role="alert"]').text()).toContain('不能超过 25 MB')

    const dropped = new File(['notes'], 'notes.md', { type: 'text/markdown' })
    await wrapper.get('.drop-zone').trigger('drop', {
      dataTransfer: { files: [dropped] },
    })
    expect(wrapper.text()).toContain('notes.md')
    await wrapper.get('.clear-file-button').trigger('click')
    expect(wrapper.find('.clear-file-button').exists()).toBe(false)

    expose(wrapper).open('text')
    await wrapper.vm.$nextTick()
    await wrapper.get('#persy-text').setValue('会失败的资料')
    mocks.ingestDocument.mockRejectedValueOnce(new Error('network down'))
    await wrapper.get('.drawer-submit').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('network down')

    await wrapper.get('button[aria-label="关闭"]').trigger('click')
    expect(wrapper.find('.import-drawer').exists()).toBe(false)
  })
})
