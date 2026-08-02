import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import { documentPreviewPip } from '@/state/documentPreviewPip'
import DocumentPreviewPictureInPicture from './DocumentPreviewPictureInPicture.vue'

describe('DocumentPreviewPictureInPicture', () => {
  beforeEach(() => {
    Object.assign(documentPreviewPip, {
      visible: true,
      minimized: false,
      title: '交付方案',
      summary: '客户定制交付闭环',
      kind: 'word',
      url: 'https://files.example.test/delivery.docx',
      fileName: 'delivery.docx',
      mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      previewRows: [],
    })
  })

  it('renders format labels and supports minimize, expand, and close', async () => {
    const wrapper = mount(DocumentPreviewPictureInPicture)

    expect(wrapper.text()).toContain('Word 文档')
    expect(wrapper.text()).toContain('W')

    await wrapper.get('button[aria-label="最小化"]').trigger('click')
    expect(documentPreviewPip.minimized).toBe(true)
    await wrapper.get('.document-pip__chip').trigger('click')
    expect(documentPreviewPip.minimized).toBe(false)
    await wrapper.get('button[aria-label="关闭"]').trigger('click')

    expect(documentPreviewPip.visible).toBe(false)
    expect(wrapper.find('.document-pip').exists()).toBe(false)
  })
})
