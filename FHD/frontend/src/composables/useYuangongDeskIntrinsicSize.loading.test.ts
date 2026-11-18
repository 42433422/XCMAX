import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { useYuangongDeskIntrinsicSize } from './useYuangongDeskIntrinsicSize'
import { YUANGONG_DESK_PNG, YUANGONG_DESK_SVG } from '@/constants/yuangongAssets'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.unstubAllGlobals() })

function setup() {
  const images: Array<{ naturalWidth: number; naturalHeight: number; src: string; onload: () => void; onerror: () => void }> = []
  vi.stubGlobal('Image', class {
    naturalWidth = 0; naturalHeight = 0; src = ''; onload = () => {}; onerror = () => {}
    constructor() { images.push(this) }
  })
  let state!: ReturnType<typeof useYuangongDeskIntrinsicSize>
  wrappers.push(mount(defineComponent({ setup() { state = useYuangongDeskIntrinsicSize(); return () => null } })))
  return { images, state }
}

describe('desk image intrinsic dimensions', () => {
  it('waits for SVG dimensions and does not load the fallback when they are valid', async () => {
    const { images, state } = setup()
    expect(state.deskIntrinsicReady.value).toBe(false)
    expect(images[0].src).toBe(YUANGONG_DESK_SVG)
    Object.assign(images[0], { naturalWidth: 192, naturalHeight: 128 })
    images[0].onload(); await flushPromises()
    expect([state.deskW.value, state.deskH.value, state.deskIntrinsicReady.value]).toEqual([192, 128, true])
    expect(images).toHaveLength(1)
  })

  it.each(['error', 'zero-size'])('uses PNG when SVG has %s', async failure => {
    const { images, state } = setup()
    if (failure === 'error') images[0].onerror()
    else images[0].onload()
    await flushPromises()
    expect(images[1].src).toBe(YUANGONG_DESK_PNG)
    expect(state.deskIntrinsicReady.value).toBe(false)
    Object.assign(images[1], { naturalWidth: 240, naturalHeight: 160 })
    images[1].onload(); await flushPromises()
    expect([state.deskW.value, state.deskH.value, state.deskIntrinsicReady.value]).toEqual([240, 160, true])
  })

  it('finishes with default dimensions if both assets fail', async () => {
    const { images, state } = setup()
    images[0].onerror(); await flushPromises()
    images[1].onerror(); await flushPromises()
    expect([state.deskW.value, state.deskH.value, state.deskIntrinsicReady.value]).toEqual([96, 64, true])
  })
})
