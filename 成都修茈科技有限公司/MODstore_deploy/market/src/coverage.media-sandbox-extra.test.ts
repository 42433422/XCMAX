import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const routeMocks = vi.hoisted(() => ({
  route: {
    query: {} as Record<string, string>,
    params: {} as Record<string, string>,
  },
  sandboxApi: {
    connectHost: vi.fn(),
    pushAndTest: vi.fn(),
  },
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeMocks.route,
}))

vi.mock('./application/sandboxApi', () => ({
  sandboxApi: routeMocks.sandboxApi,
}))

describe('MediaGenPanel coverage extras', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:pptx'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
  })

  it('generates image, video, ppt, and document outputs including error paths', async () => {
    const runner = {
      generateImages: vi.fn(async () => ['https://img.example/a.png', 'https://img.example/b.png']),
      generateVideo: vi.fn(async () => ({ status: 'done' as const, message: '视频任务完成', previewUrl: 'https://video.example/v.mp4' })),
      generatePptOutline: vi.fn(async () => '## 封面\n- 要点'),
      generatePptx: vi.fn(async () => new Blob(['pptx'])),
      generateDocument: vi.fn(async () => '# 周报\n完成重点任务'),
    }
    const Component = (await import('./components/workbench/MediaGenPanel.vue')).default
    const wrapper = mount(Component, {
      props: {
        open: true,
        initialTab: 'image',
        runner,
      },
    })
    const vm = wrapper.vm as any

    await vm.onGenImage()
    expect(runner.generateImages).not.toHaveBeenCalled()

    vm.imgPrompt = '客服海报'
    vm.imgStyle = 'photo'
    vm.imgCount = 2
    await vm.onGenImage()
    expect(vm.previewImages).toHaveLength(2)
    expect(vm.currentImageInsertText).toContain('客服海报')
    await wrapper.findAll('button').find((b) => b.text().includes('把结果插入对话'))?.trigger('click')
    expect(wrapper.emitted('insert')?.[0]?.[0]).toContain('AI 生图')

    runner.generateImages.mockRejectedValueOnce(new Error('image failed'))
    vm.imgPrompt = '失败图片'
    await vm.onGenImage()
    expect(vm.error).toContain('image failed')

    vm.setActiveTab('video')
    vm.videoPrompt = '产品宣传视频'
    await vm.onGenVideo()
    expect(vm.error).toBe('')
    expect(vm.videoResultText).toContain('预览')

    runner.generateVideo.mockRejectedValueOnce(new Error('video failed'))
    vm.videoPrompt = '失败视频'
    await vm.onGenVideo()
    expect(vm.error).toContain('video failed')

    await wrapper.setProps({
      runner: {
        ...runner,
        generateVideo: undefined,
      },
      initialTab: 'video',
    })
    await wrapper.vm.$nextTick()
    vm.videoPrompt = '没有视频能力'
    await vm.onGenVideo()
    expect(vm.error).toContain('视频生成能力')

    await wrapper.setProps({ runner, initialTab: 'ppt' })
    await wrapper.vm.$nextTick()
    vm.pptTopic = '年度经营复盘'
    vm.pptAudience = '管理层'
    vm.pptPages = 6
    await vm.onGenPpt()
    expect(vm.pptOutlineText).toContain('封面')
    expect(vm.pptDownloadUrl).toBe('blob:pptx')

    runner.generatePptOutline.mockRejectedValueOnce(new Error('ppt failed'))
    await vm.onGenPpt()
    expect(vm.error).toContain('ppt failed')

    vm.setActiveTab('doc')
    vm.docKind = 'proposal'
    vm.docInputs = '渠道合作，转化提升'
    await vm.onGenDoc()
    expect(vm.docText).toContain('周报')

    runner.generateDocument.mockRejectedValueOnce(new Error('doc failed'))
    await vm.onGenDoc()
    expect(vm.error).toContain('doc failed')

    wrapper.unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalled()
  })
})

describe('SandboxView coverage extras', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routeMocks.route.query = { host: 'https://sandbox.example.test', autoPush: 'yes' }
    routeMocks.route.params = {}
    routeMocks.sandboxApi.connectHost.mockResolvedValue({
      ok: true,
      host_url: 'https://sandbox.example.test',
      source: 'mock',
    })
    routeMocks.sandboxApi.pushAndTest.mockResolvedValue({ ok: true })
    Object.defineProperty(window, 'open', { configurable: true, value: vi.fn() })
    Object.defineProperty(HTMLIFrameElement.prototype, 'requestFullscreen', {
      configurable: true,
      value: vi.fn(),
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 200 })))
  })

  it('discovers host, pushes mod, opens host, and surfaces push/connect failures', async () => {
    const Component = (await import('./views/SandboxView.vue')).default
    const wrapper = mount(Component)
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.connected).toBe(true)
    expect(vm.statusText).toBe('已匹配')
    expect(vm.statusClass).toBe('status-ok')
    expect(vm.iframeSrc).toContain('sandbox=1')
    expect(vm.shouldAutoPush()).toBe(true)

    vm.manualModId = 'mod-1'
    vm.iframeRef = {
      contentWindow: { postMessage: vi.fn() },
      requestFullscreen: vi.fn(),
    }
    await vm.pushAndTest()
    expect(routeMocks.sandboxApi.pushAndTest).toHaveBeenCalled()
    expect(vm.pushMessage).toContain('已推送')

    routeMocks.sandboxApi.pushAndTest.mockResolvedValueOnce({ ok: false, error: 'bad mod' })
    await vm.pushAndTest()
    expect(vm.pushMessage).toContain('bad mod')

    routeMocks.sandboxApi.pushAndTest.mockRejectedValueOnce(new Error('push failed'))
    await vm.pushAndTest()
    expect(vm.pushMessage).toContain('push failed')

    vm.openHostInNewTab()
    expect(window.open).toHaveBeenCalled()
    vm.openFullscreen()
    expect(HTMLIFrameElement.prototype.requestFullscreen).toHaveBeenCalled()

    routeMocks.route.query.autoPush = '0'
    expect(vm.shouldAutoPush()).toBe(false)

    routeMocks.route.query = { host: 'https://broken.example.test' }
    routeMocks.sandboxApi.connectHost.mockRejectedValue(new Error('connect failed'))
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('browser probe failed')
    }))
    await vm.discoverAndConnect()
    expect(vm.connected).toBe(false)
    expect(vm.connectError).toContain('connect failed')

    wrapper.unmount()
  })
})
