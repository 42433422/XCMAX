import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import DodecaMediaPanel from './DodecaMediaPanel.vue'

function mountComponent(propsOverrides = {}) {
  return mount(DodecaMediaPanel, {
    props: {
      visible: true,
      items: [],
      mediaType: 'image',
      title: '媒体浏览',
      isWorkMode: false,
      ...propsOverrides,
    },
  })
}

describe('DodecaMediaPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('renders with default props', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.dodeca-media-panel').exists()).toBe(true)
  })

  it('applies visible class when visible prop is true', () => {
    const wrapper = mountComponent({ visible: true })
    expect(wrapper.find('.dodeca-media-panel').classes()).toContain('visible')
  })

  it('does not apply visible class when visible prop is false', () => {
    const wrapper = mountComponent({ visible: false })
    expect(wrapper.find('.dodeca-media-panel').classes()).not.toContain('visible')
  })

  it('applies work-mode class when isWorkMode is true', () => {
    const wrapper = mountComponent({ isWorkMode: true })
    expect(wrapper.find('.dodeca-media-panel').classes()).toContain('work-mode')
  })

  it('renders title from props', () => {
    const wrapper = mountComponent({ title: '自定义标题' })
    expect(wrapper.find('.panel-title').text()).toBe('自定义标题')
  })

  it('renders counter showing current index and total items', () => {
    const wrapper = mountComponent({
      items: [
        { type: 'image', url: 'img1.jpg', alt: 'Image 1' },
        { type: 'image', url: 'img2.jpg', alt: 'Image 2' },
      ],
    })
    expect(wrapper.find('.panel-counter').text()).toBe('1 / 2')
  })

  it('emits close event when close button is clicked', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.close-btn').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('shows empty media state when no items', () => {
    const wrapper = mountComponent({ items: [] })
    expect(wrapper.find('.empty-media').exists()).toBe(true)
    expect(wrapper.find('.empty-text').text()).toContain('暂无图片')
  })

  it('shows video empty text when mediaType is video', () => {
    const wrapper = mountComponent({ items: [], mediaType: 'video' })
    expect(wrapper.find('.empty-text').text()).toContain('暂无视频')
  })

  it('shows image when current item is image type', () => {
    const wrapper = mountComponent({
      items: [{ type: 'image', url: 'test.jpg', alt: 'Test Image' }],
    })
    const img = wrapper.find('.media-image')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe('test.jpg')
    expect(img.attributes('alt')).toBe('Test Image')
  })

  it('shows video when current item is video type', () => {
    const wrapper = mountComponent({
      items: [{ type: 'video', url: 'test.mp4' }],
    })
    const video = wrapper.find('.media-video')
    expect(video.exists()).toBe(true)
    expect(video.attributes('src')).toBe('test.mp4')
  })

  it('shows navigation when multiple items exist', () => {
    const wrapper = mountComponent({
      items: [
        { type: 'image', url: 'img1.jpg', alt: '1' },
        { type: 'image', url: 'img2.jpg', alt: '2' },
      ],
    })
    expect(wrapper.find('.panel-navigation').exists()).toBe(true)
  })

  it('hides navigation when only one item', () => {
    const wrapper = mountComponent({
      items: [{ type: 'image', url: 'img1.jpg', alt: '1' }],
    })
    expect(wrapper.find('.panel-navigation').exists()).toBe(false)
  })

  it('prev button is disabled at first item', () => {
    const wrapper = mountComponent({
      items: [
        { type: 'image', url: 'img1.jpg', alt: '1' },
        { type: 'image', url: 'img2.jpg', alt: '2' },
      ],
    })
    expect(wrapper.find('.nav-btn.prev').attributes('disabled')).toBeDefined()
  })

  it('next button is disabled at last item', async () => {
    const wrapper = mountComponent({
      items: [
        { type: 'image', url: 'img1.jpg', alt: '1' },
        { type: 'image', url: 'img2.jpg', alt: '2' },
      ],
    })
    // Navigate to last item
    await wrapper.find('.nav-btn.next').trigger('click')
    await vi.advanceTimersByTimeAsync(600)
    expect(wrapper.find('.nav-btn.next').attributes('disabled')).toBeDefined()
  })

  it('clicking next advances to next item', async () => {
    const wrapper = mountComponent({
      items: [
        { type: 'image', url: 'img1.jpg', alt: '1' },
        { type: 'image', url: 'img2.jpg', alt: '2' },
      ],
    })
    await wrapper.find('.nav-btn.next').trigger('click')
    await vi.advanceTimersByTimeAsync(600)
    expect(wrapper.find('.panel-counter').text()).toBe('2 / 2')
    expect(wrapper.find('.media-image').attributes('src')).toBe('img2.jpg')
  })

  it('clicking prev goes to previous item', async () => {
    const wrapper = mountComponent({
      items: [
        { type: 'image', url: 'img1.jpg', alt: '1' },
        { type: 'image', url: 'img2.jpg', alt: '2' },
      ],
    })
    // Go to second item first
    await wrapper.find('.nav-btn.next').trigger('click')
    await vi.advanceTimersByTimeAsync(600)
    // Go back
    await wrapper.find('.nav-btn.prev').trigger('click')
    await vi.advanceTimersByTimeAsync(600)
    expect(wrapper.find('.panel-counter').text()).toBe('1 / 2')
  })

  it('emits change event when navigating', async () => {
    const wrapper = mountComponent({
      items: [
        { type: 'image', url: 'img1.jpg', alt: '1' },
        { type: 'image', url: 'img2.jpg', alt: '2' },
      ],
    })
    await wrapper.find('.nav-btn.next').trigger('click')
    await vi.advanceTimersByTimeAsync(600)
    expect(wrapper.emitted('change')).toBeTruthy()
    expect(wrapper.emitted('change')![0][0]).toBe(1) // index
  })

  it('clicking thumbnail navigates to that item', async () => {
    const wrapper = mountComponent({
      items: [
        { type: 'image', url: 'img1.jpg', alt: '1' },
        { type: 'image', url: 'img2.jpg', alt: '2' },
        { type: 'image', url: 'img3.jpg', alt: '3' },
      ],
    })
    const thumbnails = wrapper.findAll('.thumbnail')
    await thumbnails[2].trigger('click')
    await vi.advanceTimersByTimeAsync(600)
    expect(wrapper.find('.panel-counter').text()).toBe('3 / 3')
  })

  it('shows loading state after navigation', async () => {
    const wrapper = mountComponent({
      items: [
        { type: 'image', url: 'img1.jpg', alt: '1' },
        { type: 'image', url: 'img2.jpg', alt: '2' },
      ],
    })
    await wrapper.find('.nav-btn.next').trigger('click')
    // Loading state should be visible immediately
    expect(wrapper.find('.loading-state').exists()).toBe(true)
    await vi.advanceTimersByTimeAsync(600)
    // After timeout, loading should be gone
    expect(wrapper.find('.loading-state').exists()).toBe(false)
  })

  it('shows thumbnail image when available', () => {
    const wrapper = mountComponent({
      items: [
        { type: 'image', url: 'img1.jpg', alt: '1', thumbnail: 'thumb1.jpg' },
        { type: 'image', url: 'img2.jpg', alt: '2', thumbnail: 'thumb2.jpg' },
      ],
    })
    const thumbImgs = wrapper.findAll('.thumbnail img')
    expect(thumbImgs.length).toBe(2)
    expect(thumbImgs[0].attributes('src')).toBe('thumb1.jpg')
  })

  it('shows thumbnail placeholder when no thumbnail', () => {
    const wrapper = mountComponent({
      items: [
        { type: 'image', url: 'img1.jpg', alt: '1' },
        { type: 'image', url: 'img2.jpg', alt: '2' },
      ],
    })
    expect(wrapper.find('.thumbnail-placeholder').exists()).toBe(true)
  })

  it('renders 12 dodeca faces', () => {
    const wrapper = mountComponent()
    const faces = wrapper.findAll('.dodeca-face')
    expect(faces.length).toBe(12)
  })

  it('renders scan line', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.scan-line').exists()).toBe(true)
  })

  it('handles image error', async () => {
    const wrapper = mountComponent({
      items: [{ type: 'image', url: 'bad.jpg', alt: 'Bad' }],
    })
    await wrapper.find('.media-image').trigger('error')
    // Error state is handled internally
  })
})
