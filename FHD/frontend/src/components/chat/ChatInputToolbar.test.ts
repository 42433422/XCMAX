import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatInputToolbar from './ChatInputToolbar.vue'

describe('ChatInputToolbar upload', () => {
  it('opens hidden file input on upload click', async () => {
    const click = vi.fn()
    const wrapper = mount(ChatInputToolbar, {
      props: {
        excelAnalyzeUploading: false,
        multimodalPendingCount: 0,
        clientModeTiersUiEnabled: false,
        proIntentExperienceEnabled: false,
        autoRefreshStarredWechat: false,
        ttsEnabled: false,
      },
      global: {
        mocks: {
          $t: (key: string) => key,
        },
      },
    })

    const input = wrapper.find('input[type="file"]').element as HTMLInputElement
    input.click = click

    await wrapper.get('[data-tutorial-id="toolbar-excel-analyze"]').trigger('click')

    expect(click).toHaveBeenCalled()
    expect(wrapper.emitted('trigger-upload')).toHaveLength(1)
    const registered = wrapper.emitted('register-excel-input') || []
    expect(registered.some((args) => args[0] === input)).toBe(true)
  })
})
