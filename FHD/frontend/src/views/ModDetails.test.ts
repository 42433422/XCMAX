import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import ModDetails from './ModDetails.vue'

const { apiFetch, appAlert } = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  appAlert: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/utils/apiBase', () => ({ apiFetch }))
vi.mock('@/utils/appDialog', () => ({ appAlert }))

function makeMod(overrides = {}) {
  return {
    id: 'mod-1',
    name: '测试MOD',
    author: 'Tester',
    version: '1.0.0',
    description: '一个测试用的MOD',
    is_installed: false,
    dependencies: {},
    ...overrides,
  }
}

function mockDetailsResponse(data = {}) {
  apiFetch.mockResolvedValue({
    json: () =>
      Promise.resolve({
        success: true,
        data: {
          statistics: {
            total_downloads: 100,
            avg_rating: 4.5,
            rating_count: 20,
            total_updates: 3,
          },
          ratings: [
            { id: 'r1', rating: 5, comment: '很好', user_id: 'user1', created_at: '2024-01-01T00:00:00Z' },
            { id: 'r2', rating: 3, comment: '', user_id: '', created_at: '2024-02-01T00:00:00Z' },
          ],
          ...data,
        },
      }),
  })
}

function mountMod(modOverrides = {}) {
  return mount(ModDetails, {
    props: { mod: makeMod(modOverrides) },
  })
}

describe('ModDetails.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockDetailsResponse()
  })

  it('renders mod header with name and author', () => {
    const wrapper = mountMod()
    expect(wrapper.find('.mod-title').text()).toBe('测试MOD')
    expect(wrapper.find('.mod-author').text()).toBe('by Tester')
  })

  it('shows Unknown author when not provided', () => {
    const wrapper = mountMod({ author: '' })
    expect(wrapper.find('.mod-author').text()).toBe('by Unknown')
  })

  it('renders version badge', () => {
    const wrapper = mountMod()
    expect(wrapper.find('.version').text()).toBe('v1.0.0')
  })

  it('shows installed badge when mod is installed', () => {
    const wrapper = mountMod({ is_installed: true })
    expect(wrapper.find('.badge').text()).toBe('已安装')
  })

  it('does not show installed badge when mod is not installed', () => {
    const wrapper = mountMod({ is_installed: false })
    expect(wrapper.find('.badge').exists()).toBe(false)
  })

  it('renders description section', () => {
    const wrapper = mountMod()
    expect(wrapper.find('.description').text()).toBe('一个测试用的MOD')
  })

  it('shows default description when not provided', () => {
    const wrapper = mountMod({ description: '' })
    expect(wrapper.find('.description').text()).toBe('暂无描述')
  })

  it('renders dependencies section when dependencies exist', () => {
    const wrapper = mountMod({
      dependencies: { xcagi: '1.0.0', moddep: '2.0.0' },
    })
    expect(wrapper.find('.dependencies-list').exists()).toBe(true)
    const deps = wrapper.findAll('.dependency-item')
    expect(deps).toHaveLength(2)
    expect(deps[0].find('.dep-name').text()).toBe('xcagi')
    expect(deps[0].find('.dep-version').text()).toBe('1.0.0')
  })

  it('does not render dependencies section when empty', () => {
    const wrapper = mountMod({ dependencies: {} })
    expect(wrapper.find('.dependencies-list').exists()).toBe(false)
  })

  it('marks all dependencies as satisfied', () => {
    const wrapper = mountMod({
      dependencies: { xcagi: '1.0.0', other: '2.0.0' },
    })
    const deps = wrapper.findAll('.dependency-item')
    expect(deps[0].classes()).toContain('satisfied')
    expect(deps[1].classes()).toContain('satisfied')
  })

  it('shows install button when not installed', () => {
    const wrapper = mountMod({ is_installed: false })
    const btn = wrapper.find('.action-buttons .btn-primary')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('安装 MOD')
  })

  it('shows uninstall button when installed', () => {
    const wrapper = mountMod({ is_installed: true })
    const btn = wrapper.find('.action-buttons .btn-secondary')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('卸载 MOD')
  })

  it('disables install button when installation in progress', () => {
    const wrapper = mountMod({ is_installed: false, installationInProgress: true })
    expect(wrapper.find('.action-buttons .btn-primary').text()).toContain('安装中')
    expect(wrapper.find('.action-buttons .btn-primary').attributes('disabled')).toBeDefined()
  })

  it('disables uninstall button when uninstallation in progress', () => {
    const wrapper = mountMod({ is_installed: true, uninstallationInProgress: true })
    expect(wrapper.find('.action-buttons .btn-secondary').text()).toContain('卸载中')
    expect(wrapper.find('.action-buttons .btn-secondary').attributes('disabled')).toBeDefined()
  })

  it('emits install event when install button clicked', async () => {
    const wrapper = mountMod({ is_installed: false })
    await wrapper.find('.action-buttons .btn-primary').trigger('click')
    expect(wrapper.emitted('install')).toBeTruthy()
    expect(wrapper.emitted('install')![0]).toEqual([makeMod()])
  })

  it('emits uninstall event when uninstall button clicked', async () => {
    const mod = makeMod({ is_installed: true })
    const wrapper = mount(ModDetails, { props: { mod } })
    await wrapper.find('.action-buttons .btn-secondary').trigger('click')
    expect(wrapper.emitted('uninstall')).toBeTruthy()
    expect(wrapper.emitted('uninstall')![0]).toEqual([mod])
  })

  it('does not show update button when no new version', () => {
    const wrapper = mountMod({ is_installed: true, new_version: undefined })
    expect(wrapper.find('.action-buttons .btn-warning').exists()).toBe(false)
  })

  it('shows update button when new version differs', () => {
    const wrapper = mountMod({
      is_installed: true,
      version: '1.0.0',
      new_version: '2.0.0',
    })
    expect(wrapper.find('.action-buttons .btn-warning').exists()).toBe(true)
    expect(wrapper.find('.action-buttons .btn-warning').text()).toContain('更新 MOD')
  })

  it('does not show update button when new version equals current', () => {
    const wrapper = mountMod({
      is_installed: true,
      version: '1.0.0',
      new_version: '1.0.0',
    })
    expect(wrapper.find('.action-buttons .btn-warning').exists()).toBe(false)
  })

  it('disables update button when update in progress', () => {
    const wrapper = mountMod({
      is_installed: true,
      version: '1.0.0',
      new_version: '2.0.0',
      updateInProgress: true,
    })
    expect(wrapper.find('.action-buttons .btn-warning').text()).toContain('更新中')
    expect(wrapper.find('.action-buttons .btn-warning').attributes('disabled')).toBeDefined()
  })

  it('emits update event when update button clicked', async () => {
    const mod = makeMod({ is_installed: true, version: '1.0.0', new_version: '2.0.0' })
    const wrapper = mount(ModDetails, { props: { mod } })
    await wrapper.find('.action-buttons .btn-warning').trigger('click')
    expect(wrapper.emitted('update')).toBeTruthy()
    expect(wrapper.emitted('update')![0]).toEqual([mod])
  })

  it('shows rating form when mod is not installed', () => {
    const wrapper = mountMod({ is_installed: false })
    expect(wrapper.find('.rating-form').exists()).toBe(true)
  })

  it('hides rating form when mod is installed', () => {
    const wrapper = mountMod({ is_installed: true })
    expect(wrapper.find('.rating-form').exists()).toBe(false)
  })

  it('disables submit rating button when userRating is 0', () => {
    const wrapper = mountMod({ is_installed: false })
    expect(wrapper.find('.rating-form .btn-primary').attributes('disabled')).toBeDefined()
  })

  it('loads details on mount', () => {
    mountMod()
    expect(apiFetch).toHaveBeenCalledWith('/api/mod-store/mod/mod-1/details')
  })

  it('shows no-ratings message when ratings are empty', async () => {
    apiFetch.mockResolvedValue({
      json: () =>
        Promise.resolve({
          success: true,
          data: { statistics: null, ratings: [] },
        }),
    })
    const wrapper = mountMod()
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.no-ratings').exists()).toBe(true)
    expect(wrapper.find('.no-ratings').text()).toContain('暂无评价')
  })

  it('handles load details failure gracefully', async () => {
    apiFetch.mockRejectedValue(new Error('network'))
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const wrapper = mountMod()
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(consoleSpy).toHaveBeenCalled()
    consoleSpy.mockRestore()
  })

  it('handles load details returning non-success', async () => {
    apiFetch.mockResolvedValue({
      json: () => Promise.resolve({ success: false }),
    })
    const wrapper = mountMod()
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.no-ratings').exists()).toBe(true)
  })

  it('shows statistics section after loading', async () => {
    const wrapper = mountMod()
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.stats-grid').exists()).toBe(true)
    const stats = wrapper.findAll('.stat-value')
    expect(stats[0].text()).toBe('100')
    expect(stats[1].text()).toBe('4.5')
    expect(stats[2].text()).toBe('20')
    expect(stats[3].text()).toBe('3')
  })

  it('shows ratings list after loading', async () => {
    const wrapper = mountMod()
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    const ratings = wrapper.findAll('.rating-item')
    expect(ratings).toHaveLength(2)
    expect(ratings[0].find('.rating-comment').text()).toBe('很好')
  })

  it('shows anonymous user when rating has no user_id', async () => {
    const wrapper = mountMod()
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    const users = wrapper.findAll('.rating-user')
    expect(users[1].text()).toContain('匿名用户')
  })

  it('renders default icon when mod has no icon', () => {
    const wrapper = mountMod({ icon: '' })
    const icon = wrapper.find('.mod-icon-large i')
    expect(icon.classes()).toContain('fa')
    expect(icon.classes()).toContain('fa-puzzle-piece')
  })

  it('renders custom icon when provided', () => {
    const wrapper = mountMod({ icon: 'fa fa-cube' })
    const icon = wrapper.find('.mod-icon-large i')
    expect(icon.classes()).toContain('fa-cube')
  })

  it('submitRating alerts when rating is 0', async () => {
    const wrapper = mountMod({ is_installed: false })
    // userRating defaults to 0; button is disabled, so call method directly
    await wrapper.vm.submitRating()
    expect(appAlert).toHaveBeenCalledWith('请选择评分')
  })

  it('submitRating submits rating successfully', async () => {
    apiFetch
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ success: true, data: { statistics: null, ratings: [] } }),
      })
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ success: true }),
      })
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ success: true, data: { statistics: null, ratings: [] } }),
      })
    const wrapper = mountMod({ is_installed: false })
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    // Click star 5
    const stars = wrapper.findAll('.star-rating i')
    await stars[4].trigger('click')
    await wrapper.find('.rating-form .btn-primary').trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    expect(appAlert).toHaveBeenCalledWith('评价成功！')
  })

  it('submitRating handles API failure with error message', async () => {
    apiFetch
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ success: true, data: { statistics: null, ratings: [] } }),
      })
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ success: false, error: '评分失败原因' }),
      })
    const wrapper = mountMod({ is_installed: false })
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    const stars = wrapper.findAll('.star-rating i')
    await stars[4].trigger('click')
    await wrapper.find('.rating-form .btn-primary').trigger('click')
    await wrapper.vm.$nextTick()
    expect(appAlert).toHaveBeenCalledWith('评价失败：评分失败原因')
  })

  it('submitRating handles network error', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    apiFetch
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ success: true, data: { statistics: null, ratings: [] } }),
      })
      .mockRejectedValueOnce(new Error('network'))
    const wrapper = mountMod({ is_installed: false })
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    const stars = wrapper.findAll('.star-rating i')
    await stars[4].trigger('click')
    await wrapper.find('.rating-form .btn-primary').trigger('click')
    await wrapper.vm.$nextTick()
    expect(appAlert).toHaveBeenCalledWith('评价失败，请重试')
    consoleSpy.mockRestore()
  })
})
