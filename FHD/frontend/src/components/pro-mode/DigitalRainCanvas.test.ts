import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

const startMock = vi.fn()
const stopMock = vi.fn()
const setWorkModeMock = vi.fn()
const resizeMock = vi.fn()
const clearMock = vi.fn()
const isRunningRef = ref(false)

vi.mock('@/composables/useDigitalRain', () => ({
  useDigitalRain: () => ({
    isRunning: isRunningRef,
    start: startMock,
    stop: stopMock,
    setWorkMode: setWorkModeMock,
    resize: resizeMock,
    clear: clearMock,
  }),
}))

import DigitalRainCanvas from './DigitalRainCanvas.vue'

describe('DigitalRainCanvas', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    isRunningRef.value = false
  })

  it('renders the canvas element', () => {
    const wrapper = mount(DigitalRainCanvas, {
      props: { isActive: false },
    })
    expect(wrapper.find('canvas.digital-rain').exists()).toBe(true)
  })

  it('hides canvas when isActive is false', () => {
    const wrapper = mount(DigitalRainCanvas, {
      props: { isActive: false },
    })
    expect(wrapper.find('canvas').attributes('style')).toContain('display: none')
  })

  it('shows canvas when isActive is true', () => {
    const wrapper = mount(DigitalRainCanvas, {
      props: { isActive: true },
    })
    expect(wrapper.find('canvas').attributes('style')).toContain('display: block')
  })

  it('does not apply work-mode class when isWorkMode is false', () => {
    const wrapper = mount(DigitalRainCanvas, {
      props: { isActive: true, isWorkMode: false },
    })
    expect(wrapper.find('canvas').classes()).not.toContain('work-mode')
  })

  it('applies work-mode class when isWorkMode is true', () => {
    const wrapper = mount(DigitalRainCanvas, {
      props: { isActive: true, isWorkMode: true },
    })
    expect(wrapper.find('canvas').classes()).toContain('work-mode')
  })

  it('emits ready event on mount', () => {
    const wrapper = mount(DigitalRainCanvas, {
      props: { isActive: false },
    })
    expect(wrapper.emitted('ready')).toBeTruthy()
  })

  it('calls start on mount when autoStart and isActive are true', () => {
    mount(DigitalRainCanvas, {
      props: { isActive: true, autoStart: true },
    })
    expect(startMock).toHaveBeenCalled()
  })

  it('does not call start on mount when isActive is false', () => {
    mount(DigitalRainCanvas, {
      props: { isActive: false, autoStart: true },
    })
    expect(startMock).not.toHaveBeenCalled()
  })

  it('does not call start on mount when autoStart is false', () => {
    mount(DigitalRainCanvas, {
      props: { isActive: true, autoStart: false },
    })
    expect(startMock).not.toHaveBeenCalled()
  })

  it('calls setWorkMode when isWorkMode prop changes', async () => {
    const wrapper = mount(DigitalRainCanvas, {
      props: { isActive: false, isWorkMode: false },
    })
    setWorkModeMock.mockClear()
    await wrapper.setProps({ isWorkMode: true })
    expect(setWorkModeMock).toHaveBeenCalledWith(true)
  })

  it('calls start when isActive changes from false to true and not running', async () => {
    isRunningRef.value = false
    const wrapper = mount(DigitalRainCanvas, {
      props: { isActive: false, autoStart: false },
    })
    startMock.mockClear()
    await wrapper.setProps({ isActive: true })
    expect(startMock).toHaveBeenCalled()
  })

  it('calls stop when isActive changes from true to false and running', async () => {
    isRunningRef.value = true
    const wrapper = mount(DigitalRainCanvas, {
      props: { isActive: true, autoStart: false },
    })
    stopMock.mockClear()
    await wrapper.setProps({ isActive: false })
    expect(stopMock).toHaveBeenCalled()
  })

  it('does not call start when isActive becomes true but already running', async () => {
    isRunningRef.value = true
    const wrapper = mount(DigitalRainCanvas, {
      props: { isActive: false, autoStart: false },
    })
    startMock.mockClear()
    await wrapper.setProps({ isActive: true })
    expect(startMock).not.toHaveBeenCalled()
  })

  it('calls resize on window resize event', async () => {
    mount(DigitalRainCanvas, {
      props: { isActive: false },
    })
    resizeMock.mockClear()
    window.dispatchEvent(new Event('resize'))
    expect(resizeMock).toHaveBeenCalled()
  })

  it('calls stop on unmount', () => {
    const wrapper = mount(DigitalRainCanvas, {
      props: { isActive: false },
    })
    stopMock.mockClear()
    wrapper.unmount()
    expect(stopMock).toHaveBeenCalled()
  })
})
