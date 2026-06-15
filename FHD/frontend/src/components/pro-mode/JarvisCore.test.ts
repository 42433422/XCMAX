import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/utils/geometry-real', () => ({
  createIcosahedron: (radius: number) => ({
    faces: Array.from({ length: 20 }, (_, i) => ({
      normal: [Math.cos(i * 0.3), Math.sin(i * 0.3), 0],
      vertices: [[0, 0, radius], [radius, 0, 0], [0, radius, 0]],
    })),
  }),
  createOctahedron: (radius: number) => ({
    faces: Array.from({ length: 8 }, (_, i) => ({
      normal: [Math.cos(i * 0.8), Math.sin(i * 0.8), 0.5],
      vertices: [[0, 0, radius], [radius, 0, 0], [0, radius, 0]],
    })),
  }),
  createTetrahedron: (radius: number) => ({
    faces: Array.from({ length: 4 }, (_, i) => ({
      normal: [Math.cos(i * 1.5), Math.sin(i * 1.5), 0.3],
      vertices: [[0, 0, radius], [radius, 0, 0], [0, radius, 0]],
    })),
  }),
  createDodecahedron: (radius: number) => ({
    faces: Array.from({ length: 12 }, (_, i) => ({
      normal: [Math.cos(i * 0.5), Math.sin(i * 0.5), 0.2],
      vertices: [[0, 0, radius], [radius, 0, 0], [0, radius, 0]],
    })),
  }),
}))

import JarvisCore from '@/components/pro-mode/JarvisCore.vue'

describe('JarvisCore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.spyOn(global, 'requestAnimationFrame').mockImplementation((cb: FrameRequestCallback) => {
      return 0
    })
    vi.spyOn(global, 'cancelAnimationFrame').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the core container', () => {
    const wrapper = mount(JarvisCore)
    expect(wrapper.find('.jarvis-core').exists()).toBe(true)
  })

  it('renders the sphere element', () => {
    const wrapper = mount(JarvisCore)
    expect(wrapper.find('.jarvis-sphere').exists()).toBe(true)
  })

  it('applies speaking class when isSpeaking is true', () => {
    const wrapper = mount(JarvisCore, { props: { isSpeaking: true } })
    expect(wrapper.find('.jarvis-core').classes()).toContain('speaking')
  })

  it('does not apply speaking class when isSpeaking is false', () => {
    const wrapper = mount(JarvisCore, { props: { isSpeaking: false } })
    expect(wrapper.find('.jarvis-core').classes()).not.toContain('speaking')
  })

  it('applies work-mode class when isWorkMode is true', () => {
    const wrapper = mount(JarvisCore, { props: { isWorkMode: true } })
    expect(wrapper.find('.jarvis-core').classes()).toContain('work-mode')
  })

  it('applies monitor-mode class when isMonitorMode is true', () => {
    const wrapper = mount(JarvisCore, { props: { isMonitorMode: true } })
    expect(wrapper.find('.jarvis-core').classes()).toContain('monitor-mode')
  })

  it('emits click event when clicked', async () => {
    const wrapper = mount(JarvisCore)
    await wrapper.find('.jarvis-core').trigger('click')
    expect(wrapper.emitted('click')).toBeTruthy()
  })

  it('renders icosa polyhedron', () => {
    const wrapper = mount(JarvisCore)
    expect(wrapper.find('.polyhedron.icosa').exists()).toBe(true)
  })

  it('renders octa polyhedron', () => {
    const wrapper = mount(JarvisCore)
    expect(wrapper.find('.polyhedron.octa').exists()).toBe(true)
  })

  it('renders tetra polyhedron', () => {
    const wrapper = mount(JarvisCore)
    expect(wrapper.find('.polyhedron.tetra').exists()).toBe(true)
  })

  it('renders dodeca polyhedron', () => {
    const wrapper = mount(JarvisCore)
    expect(wrapper.find('.polyhedron.dodeca').exists()).toBe(true)
  })

  it('generates face elements for each polyhedron', () => {
    const wrapper = mount(JarvisCore)
    const vm = wrapper.vm as any
    expect(vm.icosaFaces.length).toBe(20)
    expect(vm.octaFaces.length).toBe(8)
    expect(vm.tetraFaces.length).toBe(4)
    expect(vm.dodecaFaces.length).toBe(12)
  })

  it('computes coreTransform with scale when speaking', () => {
    const wrapper = mount(JarvisCore, { props: { isSpeaking: true } })
    const vm = wrapper.vm as any
    expect(vm.coreTransform).toContain('scale(1.1)')
  })

  it('computes coreTransform with scale 1 when not speaking', () => {
    const wrapper = mount(JarvisCore, { props: { isSpeaking: false } })
    const vm = wrapper.vm as any
    expect(vm.coreTransform).toContain('scale(1)')
  })

  it('computes icosaTransform from rotation', () => {
    const wrapper = mount(JarvisCore)
    const vm = wrapper.vm as any
    expect(vm.icosaTransform).toContain('rotateX')
    expect(vm.icosaTransform).toContain('rotateY')
    expect(vm.icosaTransform).toContain('rotateZ')
  })

  it('computes octaTransform with 1.2x rotation multiplier', () => {
    const wrapper = mount(JarvisCore)
    const vm = wrapper.vm as any
    const rx = vm.rotation.x
    expect(vm.octaTransform).toContain(`rotateX(${rx * 1.2}deg)`)
  })

  it('computes tetraTransform with 1.5x rotation multiplier', () => {
    const wrapper = mount(JarvisCore)
    const vm = wrapper.vm as any
    const rx = vm.rotation.x
    expect(vm.tetraTransform).toContain(`rotateX(${rx * 1.5}deg)`)
  })

  it('computes dodecaTransform with 0.8x rotation multiplier', () => {
    const wrapper = mount(JarvisCore)
    const vm = wrapper.vm as any
    const rx = vm.rotation.x
    expect(vm.dodecaTransform).toContain(`rotateX(${rx * 0.8}deg)`)
  })

  it('faceTransform handles face with normal', () => {
    const wrapper = mount(JarvisCore)
    const vm = wrapper.vm as any
    const face = { normal: [0, 0, 1], vertices: [[0, 0, 50], [50, 0, 0], [0, 50, 0]] }
    const result = vm.faceTransform(face, 0, 10)
    expect(result).toContain('rotateX')
    expect(result).toContain('rotateY')
    expect(result).toContain('translateZ')
  })

  it('faceTransform handles face without normal (fallback)', () => {
    const wrapper = mount(JarvisCore)
    const vm = wrapper.vm as any
    const face = { vertices: [] }
    const result = vm.faceTransform(face, 0, 10)
    expect(result).toContain('translateZ')
  })

  it('faceTransform handles face with null normal', () => {
    const wrapper = mount(JarvisCore)
    const vm = wrapper.vm as any
    const face = { normal: null, vertices: [] }
    const result = vm.faceTransform(face, 0, 10)
    expect(result).toContain('translateZ')
  })

  it('increments rotation on mount via animate', () => {
    const wrapper = mount(JarvisCore)
    const vm = wrapper.vm as any
    // animate() runs once on mount, incrementing rotation
    expect(vm.rotation.x).toBe(0.2)
    expect(vm.rotation.y).toBe(0.3)
    expect(vm.rotation.z).toBe(0.1)
  })

  it('cancels animation frame on unmount', () => {
    const wrapper = mount(JarvisCore)
    const vm = wrapper.vm as any
    vm.animationId = 123
    wrapper.unmount()
    expect(vi.spyOn(global, 'cancelAnimationFrame')).toBeDefined()
  })

  it('does not cancel animation if animationId is null on unmount', () => {
    const cancelSpy = vi.spyOn(global, 'cancelAnimationFrame')
    cancelSpy.mockClear()
    const wrapper = mount(JarvisCore)
    const vm = wrapper.vm as any
    vm.animationId = null
    wrapper.unmount()
    // cancelAnimationFrame should not be called with null animationId
    const calls = cancelSpy.mock.calls.filter(c => c[0] !== 0)
    expect(calls.length).toBe(0)
  })
})
