import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatInputToolbar from './ChatInputToolbar.vue'
import { useApprovalMode } from '@/composables/useApprovalMode'

function mountToolbar(propsOverrides = {}) {
  return mount(ChatInputToolbar, {
    props: {
      attachmentUploading: false,
      multimodalPendingCount: 0,
      ...propsOverrides,
    },
    global: {
      mocks: {
        $t: (key: string) => key,
      },
    },
  })
}

describe('ChatInputToolbar', () => {
  beforeEach(() => {
    const { setEnabled, setMode } = useApprovalMode()
    setEnabled(false)
    setMode('manual')
  })

  it('renders toolbar container', () => {
    const wrapper = mountToolbar()
    expect(wrapper.find('.input-toolbar').exists()).toBe(true)
    expect(wrapper.find('#newConversationBtn').exists()).toBe(false)
  })

  it('renders approval mode toggle button', () => {
    const wrapper = mountToolbar()
    const btn = wrapper.find('#approvalModeBtn')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('chat.approvalMode')
  })

  it('does not show approval choices when disabled', () => {
    const wrapper = mountToolbar()
    expect(wrapper.find('.approval-mode__choices').exists()).toBe(false)
  })

  it('renders separate icon-only upload and office parsing buttons', () => {
    const wrapper = mountToolbar()
    const upload = wrapper.get('button[data-tutorial-id="toolbar-excel-analyze"]')
    const parse = wrapper.get('button[data-tutorial-id="toolbar-office-docking"]')
    expect(upload.attributes('aria-label')).toBe('chat.uploadAttachment')
    expect(parse.attributes('aria-label')).toBe('chat.officeDocking')
    for (const button of [upload, parse]) {
      expect(button.get('svg').attributes()).toHaveProperty('viewBox')
      expect(button.text()).toBe('')
    }
  })

  it('shows manual/auto choices when approval toggled on', async () => {
    const wrapper = mountToolbar()
    await wrapper.find('#approvalModeBtn').trigger('click')
    expect(wrapper.find('.approval-mode__choices').exists()).toBe(true)
    expect(wrapper.find('#approvalModeBtn').attributes('aria-pressed')).toBe('true')
  })

  it('selects auto mode when auto choice clicked', async () => {
    const wrapper = mountToolbar()
    await wrapper.find('#approvalModeBtn').trigger('click')
    const choices = wrapper.findAll('.approval-mode__choice')
    await choices[1].trigger('click')
    expect(choices[1].classes()).toContain('is-active')
  })

  it('opens hidden file input on upload click', async () => {
    const click = vi.fn()
    const wrapper = mountToolbar()
    const input = wrapper.find('input[type="file"]').element as HTMLInputElement
    input.click = click
    await wrapper.get('[data-tutorial-id="toolbar-excel-analyze"]').trigger('click')
    expect(click).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('trigger-upload')).toBeUndefined()
  })

  it('routes office parsing separately from attachment upload', async () => {
    const wrapper = mountToolbar()
    await wrapper.get('[data-tutorial-id="toolbar-office-docking"]').trigger('click')
    expect(wrapper.emitted('trigger-office-docking')).toHaveLength(1)
    expect(wrapper.emitted('attachment-file-change')).toBeUndefined()
  })

  it('only keeps the attachment input so folder upload is not duplicated', () => {
    const wrapper = mountToolbar()
    const inputs = wrapper.findAll('input[type="file"]')
    expect(inputs.length).toBe(1)
    expect(inputs[0].attributes('webkitdirectory')).toBeUndefined()
    expect(wrapper.findAll('.toolbar-btn').some((b) => b.text().includes('chat.uploadFolder'))).toBe(
      false,
    )
  })

  it('upload button is disabled when attachmentUploading is true', () => {
    const wrapper = mountToolbar({ attachmentUploading: true })
    const btn = wrapper.find('[data-tutorial-id="toolbar-excel-analyze"]')
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('upload button is enabled when attachmentUploading is false', () => {
    const wrapper = mountToolbar({ attachmentUploading: false })
    const btn = wrapper.find('[data-tutorial-id="toolbar-excel-analyze"]')
    expect(btn.attributes('disabled')).toBeUndefined()
  })

  it('shows upload progress', () => {
    const wrapper = mountToolbar({ attachmentUploading: true })
    const btn = wrapper.find('[data-tutorial-id="toolbar-excel-analyze"]')
    expect(btn.attributes('aria-label')).toBe('shell.uploadingAttachment')
    expect(btn.find('.is-loading').exists()).toBe(true)
  })

  it('shows office parsing progress independently of upload', () => {
    const wrapper = mountToolbar({ officeDockingProcessing: true })
    const parse = wrapper.get('[data-tutorial-id="toolbar-office-docking"]')
    expect(parse.attributes('disabled')).toBeDefined()
    expect(parse.attributes('aria-label')).toBe('chat.officeDockingBusy')
    expect(parse.find('.is-loading').exists()).toBe(true)
    expect(wrapper.get('[data-tutorial-id="toolbar-excel-analyze"]').attributes('disabled')).toBeUndefined()
  })

  it('announces the attachment count while keeping the button icon-only', () => {
    const wrapper = mountToolbar({ multimodalPendingCount: 3 })
    const upload = wrapper.get('[data-tutorial-id="toolbar-excel-analyze"]')
    expect(upload.attributes('aria-label')).toBe('chat.uploadAttachment (3)')
    expect(upload.text()).toBe('')
  })

  it('renders hidden file input with correct accept attribute', () => {
    const wrapper = mountToolbar()
    const input = wrapper.find('input[type="file"]')
    expect(input.attributes('accept')).toContain('.xlsx')
    expect(input.attributes('accept')).toContain('.jpg')
    expect(input.attributes('accept')).toContain('.pdf')
  })

  it('file input is hidden', () => {
    const wrapper = mountToolbar()
    const input = wrapper.find('input[type="file"]')
    expect(input.attributes('style') || '').toContain('display')
    expect(input.attributes('style') || '').toContain('none')
  })

  it('file input has multiple attribute', () => {
    const wrapper = mountToolbar()
    const input = wrapper.find('input[type="file"]')
    expect(input.attributes('multiple')).toBeDefined()
  })

  it('emits attachment-file-change when file input changes', async () => {
    const wrapper = mountToolbar()
    await wrapper.find('input[type="file"]').trigger('change')
    expect(wrapper.emitted('attachment-file-change')).toHaveLength(1)
  })

  it('upload button has correct title', () => {
    const wrapper = mountToolbar()
    const btn = wrapper.find('[data-tutorial-id="toolbar-excel-analyze"]')
    expect(btn.attributes('title')).toBe('chat.uploadTitle')
  })

  it('approval mode button has correct title', () => {
    const wrapper = mountToolbar()
    expect(wrapper.find('#approvalModeBtn').attributes('title')).toBe('chat.approvalModeTitle')
  })
})
