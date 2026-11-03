import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it } from 'vitest'

import TtsSubtitleOverlay from './TtsSubtitleOverlay.vue'
import {
  beginTtsSubtitles,
  endTtsSubtitles,
  setTtsSubtitleIndex,
  useTtsSubtitleStore,
} from '../composables/ttsSubtitleStore'

describe('TtsSubtitleOverlay', () => {
  beforeEach(() => {
    endTtsSubtitles()
    document.body.innerHTML = ''
  })

  it('shows only the current spoken line', async () => {
    const gen = beginTtsSubtitles(['上一句。', '当前句。', '下一句。'])
    setTtsSubtitleIndex(1, gen)

    const wrapper = mount(TtsSubtitleOverlay, { attachTo: document.body })

    expect(document.body.textContent).toContain('当前句。')
    expect(document.body.textContent).not.toContain('上一句。')
    expect(document.body.textContent).not.toContain('下一句。')
    expect(document.body.innerHTML).toContain('tts-sub__line--cur')
    expect(document.body.innerHTML).not.toContain('tts-sub__line--prev')
    expect(document.body.innerHTML).not.toContain('tts-sub__line--next')
    expect(document.querySelector('[aria-label="朗读字幕"]')).toBeTruthy()

    const close = document.querySelector<HTMLButtonElement>('[aria-label="关闭字幕"]')
    expect(close).toBeTruthy()
    close?.click()
    await nextTick()
    expect(useTtsSubtitleStore().visible.value).toBe(false)
    expect(document.querySelector('[aria-label="朗读字幕"]')).toBeNull()

    wrapper.unmount()
  })
})
