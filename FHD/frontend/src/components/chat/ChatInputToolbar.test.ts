import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import ChatInputToolbar from './ChatInputToolbar.vue'

function mountToolbar(propsOverrides = {}) {
  return mount(ChatInputToolbar, {
    props: {
      excelAnalyzeUploading: false,
      multimodalPendingCount: 0,
      clientModeTiersUiEnabled: false,
      proIntentExperienceEnabled: false,
      autoRefreshStarredWechat: false,
      ttsEnabled: false,
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
  it('renders toolbar container', () => {
    const wrapper = mountToolbar()
    expect(wrapper.find('.input-toolbar').exists()).toBe(true)
  })

  it('renders new conversation button', () => {
    const wrapper = mountToolbar()
    const btn = wrapper.find('#newConversationBtn')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('shell.newChat')
  })

  it('renders history button', () => {
    const wrapper = mountToolbar()
    const btn = wrapper.find('#historyPanelBtn')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('shell.history')
  })

  it('renders upload button', () => {
    const wrapper = mountToolbar()
    const btn = wrapper.find('[data-tutorial-id="toolbar-excel-analyze"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('shell.upload')
  })

  it('emits new-conversation when new chat button clicked', async () => {
    const wrapper = mountToolbar()
    await wrapper.find('#newConversationBtn').trigger('click')
    expect(wrapper.emitted('new-conversation')).toHaveLength(1)
  })

  it('emits show-history when history button clicked', async () => {
    const wrapper = mountToolbar()
    await wrapper.find('#historyPanelBtn').trigger('click')
    expect(wrapper.emitted('show-history')).toHaveLength(1)
  })

  it('opens hidden file input on upload click', async () => {
    const click = vi.fn()
    const wrapper = mountToolbar()
    const input = wrapper.find('input[type="file"]').element as HTMLInputElement
    input.click = click
    await wrapper.get('[data-tutorial-id="toolbar-excel-analyze"]').trigger('click')
    expect(click).toHaveBeenCalled()
    expect(wrapper.emitted('trigger-upload')).toHaveLength(1)
  })

  it('emits register-excel-input on mount', () => {
    const wrapper = mountToolbar()
    const registered = wrapper.emitted('register-excel-input') || []
    expect(registered.length).toBeGreaterThan(0)
  })

  it('upload button is disabled when excelAnalyzeUploading is true', () => {
    const wrapper = mountToolbar({ excelAnalyzeUploading: true })
    const btn = wrapper.find('[data-tutorial-id="toolbar-excel-analyze"]')
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('upload button is enabled when excelAnalyzeUploading is false', () => {
    const wrapper = mountToolbar({ excelAnalyzeUploading: false })
    const btn = wrapper.find('[data-tutorial-id="toolbar-excel-analyze"]')
    expect(btn.attributes('disabled')).toBeUndefined()
  })

  it('shows analyzing text when uploading', () => {
    const wrapper = mountToolbar({ excelAnalyzeUploading: true })
    const btn = wrapper.find('[data-tutorial-id="toolbar-excel-analyze"]')
    expect(btn.text()).toContain('shell.uploadAnalyzing')
  })

  it('shows upload text when not uploading', () => {
    const wrapper = mountToolbar({ excelAnalyzeUploading: false })
    const btn = wrapper.find('[data-tutorial-id="toolbar-excel-analyze"]')
    expect(btn.text()).toContain('shell.upload')
    expect(btn.text()).not.toContain('shell.uploadAnalyzing')
  })

  it('shows pending count when multimodalPendingCount > 0', () => {
    const wrapper = mountToolbar({ multimodalPendingCount: 3 })
    const btn = wrapper.find('[data-tutorial-id="toolbar-excel-analyze"]')
    expect(btn.text()).toContain('(3)')
  })

  it('does not show pending count when multimodalPendingCount is 0', () => {
    const wrapper = mountToolbar({ multimodalPendingCount: 0 })
    const btn = wrapper.find('[data-tutorial-id="toolbar-excel-analyze"]')
    expect(btn.text()).not.toContain('(')
  })

  it('renders hidden file input with correct accept attribute', () => {
    const wrapper = mountToolbar()
    const input = wrapper.find('input[type="file"]')
    expect(input.attributes('accept')).toContain('.xlsx')
    expect(input.attributes('accept')).toContain('image/jpeg')
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

  it('emits excel-file-change when file input changes', async () => {
    const wrapper = mountToolbar()
    await wrapper.find('input[type="file"]').trigger('change')
    expect(wrapper.emitted('excel-file-change')).toHaveLength(1)
  })

  it('does not render pro-intent toggle when clientModeTiersUiEnabled is false', () => {
    const wrapper = mountToolbar({ clientModeTiersUiEnabled: false })
    expect(wrapper.find('.intent-pro-toggle').exists()).toBe(false)
  })

  it('renders pro-intent toggle when clientModeTiersUiEnabled is true', () => {
    const wrapper = mountToolbar({ clientModeTiersUiEnabled: true })
    expect(wrapper.find('.intent-pro-toggle').exists()).toBe(true)
  })

  it('pro-intent checkbox reflects proIntentExperienceEnabled prop', () => {
    const wrapper = mountToolbar({
      clientModeTiersUiEnabled: true,
      proIntentExperienceEnabled: true,
    })
    const checkbox = wrapper.find('.intent-pro-toggle input[type="checkbox"]')
    expect((checkbox.element as HTMLInputElement).checked).toBe(true)
  })

  it('pro-intent checkbox is unchecked when proIntentExperienceEnabled is false', () => {
    const wrapper = mountToolbar({
      clientModeTiersUiEnabled: true,
      proIntentExperienceEnabled: false,
    })
    const checkbox = wrapper.find('.intent-pro-toggle input[type="checkbox"]')
    expect((checkbox.element as HTMLInputElement).checked).toBe(false)
  })

  it('emits pro-intent-change with true when checkbox checked', async () => {
    const wrapper = mountToolbar({
      clientModeTiersUiEnabled: true,
      proIntentExperienceEnabled: false,
    })
    const checkbox = wrapper.find('.intent-pro-toggle input[type="checkbox"]')
    await checkbox.setValue(true)
    expect(wrapper.emitted('pro-intent-change')).toBeTruthy()
    expect(wrapper.emitted('pro-intent-change')![0]).toEqual([true])
  })

  it('emits pro-intent-change with false when checkbox unchecked', async () => {
    const wrapper = mountToolbar({
      clientModeTiersUiEnabled: true,
      proIntentExperienceEnabled: true,
    })
    const checkbox = wrapper.find('.intent-pro-toggle input[type="checkbox"]')
    await checkbox.setValue(false)
    expect(wrapper.emitted('pro-intent-change')![0]).toEqual([false])
  })

  it('renders auto-refresh toggle', () => {
    const wrapper = mountToolbar()
    const toggle = wrapper.find('[data-tutorial-id="star-auto-refresh-toggle"]')
    expect(toggle.exists()).toBe(true)
  })

  it('auto-refresh checkbox reflects autoRefreshStarredWechat prop', () => {
    const wrapper = mountToolbar({ autoRefreshStarredWechat: true })
    const checkbox = wrapper.find('[data-tutorial-id="star-auto-refresh-toggle"] input[type="checkbox"]')
    expect((checkbox.element as HTMLInputElement).checked).toBe(true)
  })

  it('emits auto-refresh-change when checkbox toggled', async () => {
    const wrapper = mountToolbar({ autoRefreshStarredWechat: false })
    const checkbox = wrapper.find('[data-tutorial-id="star-auto-refresh-toggle"] input[type="checkbox"]')
    await checkbox.setValue(true)
    expect(wrapper.emitted('auto-refresh-change')).toBeTruthy()
    expect(wrapper.emitted('auto-refresh-change')![0]).toEqual([true])
  })

  it('renders TTS toggle', () => {
    const wrapper = mountToolbar()
    const labels = wrapper.findAll('label')
    const ttsLabel = labels.find((l) => l.text().includes('chat.ttsToggle'))
    expect(ttsLabel).toBeTruthy()
  })

  it('TTS checkbox reflects ttsEnabled prop', () => {
    const wrapper = mountToolbar({ ttsEnabled: true })
    const checkboxes = wrapper.findAll('input[type="checkbox"]')
    const ttsCheckbox = checkboxes.find(
      (c) => (c.element as HTMLInputElement).checked === true
    )
    expect(ttsCheckbox).toBeTruthy()
  })

  it('emits toggle-tts when TTS checkbox toggled', async () => {
    const wrapper = mountToolbar({ ttsEnabled: false })
    const labels = wrapper.findAll('label')
    const ttsLabel = labels.find((l) => l.text().includes('chat.ttsToggle'))
    const checkbox = ttsLabel!.find('input[type="checkbox"]')
    await checkbox.setValue(true)
    expect(wrapper.emitted('toggle-tts')).toBeTruthy()
    expect(wrapper.emitted('toggle-tts')![0]).toEqual([true])
  })

  it('emits toggle-tts with false when unchecking TTS', async () => {
    const wrapper = mountToolbar({ ttsEnabled: true })
    const labels = wrapper.findAll('label')
    const ttsLabel = labels.find((l) => l.text().includes('chat.ttsToggle'))
    const checkbox = ttsLabel!.find('input[type="checkbox"]')
    await checkbox.setValue(false)
    expect(wrapper.emitted('toggle-tts')![0]).toEqual([false])
  })

  it('forwards file input ref to parent via excelAnalyzeInputRef', async () => {
    const parentRef = ref<HTMLInputElement | null>(null)
    const wrapper = mountToolbar({ excelAnalyzeInputRef: parentRef })
    await wrapper.vm.$nextTick()
    expect(parentRef.value).not.toBeNull()
    expect(parentRef.value).toBeInstanceOf(HTMLInputElement)
  })

  it('upload button has correct title', () => {
    const wrapper = mountToolbar()
    const btn = wrapper.find('[data-tutorial-id="toolbar-excel-analyze"]')
    expect(btn.attributes('title')).toBe('chat.uploadTitle')
  })

  it('new conversation button has correct title', () => {
    const wrapper = mountToolbar()
    expect(wrapper.find('#newConversationBtn').attributes('title')).toBe('chat.newConversationTitle')
  })

  it('history button has correct title', () => {
    const wrapper = mountToolbar()
    expect(wrapper.find('#historyPanelBtn').attributes('title')).toBe('chat.historyTitleBtn')
  })

  it('pro-intent toggle has correct title', () => {
    const wrapper = mountToolbar({ clientModeTiersUiEnabled: true })
    expect(wrapper.find('.intent-pro-toggle').attributes('title')).toBe('chat.proIntentTitle')
  })
})
