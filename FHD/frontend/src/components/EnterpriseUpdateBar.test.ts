import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  checkEnterpriseUpdates: vi.fn(),
  getEnterpriseJob: vi.fn(),
  applyEnterpriseUpdate: vi.fn(),
  isAdminConsoleSpa: vi.fn().mockReturnValue(false),
}))

vi.mock('@/api/xcmaxDeploy', () => ({
  xcmaxDeployApi: {
    checkEnterpriseUpdates: mocks.checkEnterpriseUpdates,
    getEnterpriseJob: mocks.getEnterpriseJob,
    applyEnterpriseUpdate: mocks.applyEnterpriseUpdate,
  },
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: mocks.isAdminConsoleSpa,
}))

vi.mock('@/components/Modal.vue', () => ({
  default: {
    name: 'Modal',
    props: ['modelValue', 'title', 'maxWidth'],
    emits: ['update:modelValue'],
    template: `<div v-if="modelValue" class="modal-stub"><div class="modal-stub-title">{{ title }}</div><slot /><slot name="footer" /></div>`,
  },
}))

import EnterpriseUpdateBar from './EnterpriseUpdateBar.vue'

const checkEnterpriseUpdates = mocks.checkEnterpriseUpdates
const getEnterpriseJob = mocks.getEnterpriseJob
const applyEnterpriseUpdate = mocks.applyEnterpriseUpdate
const isAdminConsoleSpa = mocks.isAdminConsoleSpa

describe('EnterpriseUpdateBar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    isAdminConsoleSpa.mockReturnValue(false)
    sessionStorage.clear()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function mountBar() {
    return mount(EnterpriseUpdateBar)
  }

  it('does not render bar when no update needed', async () => {
    checkEnterpriseUpdates.mockResolvedValue({
      data: {
        flags: { needs_update: false },
        update_hub: { sha256: 'abc', version: '1.0', git_sha: 'def' },
        enterprise: { deployed_sha256: 'xyz' },
      },
    })
    const wrapper = mountBar()
    await flushPromises()
    expect(wrapper.find('.enterprise-update-bar').exists()).toBe(false)
  })

  it('renders bar when update is needed', async () => {
    checkEnterpriseUpdates.mockResolvedValue({
      data: {
        flags: { needs_update: true },
        update_hub: { sha256: 'newsha', version: 'v1.2', git_sha: 'abc123' },
        enterprise: { deployed_sha256: 'oldsha' },
      },
    })
    const wrapper = mountBar()
    await flushPromises()
    expect(wrapper.find('.enterprise-update-bar').exists()).toBe(true)
    expect(wrapper.text()).toContain('v1.2')
    expect(wrapper.text()).toContain('abc123')
  })

  it('hides bar when checkEnterpriseUpdates fails', async () => {
    checkEnterpriseUpdates.mockRejectedValue(new Error('network'))
    const wrapper = mountBar()
    await flushPromises()
    expect(wrapper.find('.enterprise-update-bar').exists()).toBe(false)
  })

  it('does not check when in admin console spa', async () => {
    isAdminConsoleSpa.mockReturnValue(true)
    checkEnterpriseUpdates.mockResolvedValue({ data: {} })
    const wrapper = mountBar()
    await flushPromises()
    expect(checkEnterpriseUpdates).not.toHaveBeenCalled()
    expect(wrapper.find('.enterprise-update-bar').exists()).toBe(false)
  })

  it('hides bar when sha matches dismissed sha in sessionStorage', async () => {
    sessionStorage.setItem('xcagi_enterprise_update_dismiss_sha', 'dismissedsha')
    checkEnterpriseUpdates.mockResolvedValue({
      data: {
        flags: { needs_update: true },
        update_hub: { sha256: 'dismissedsha', version: '1.0', git_sha: '' },
        enterprise: { deployed_sha256: 'old' },
      },
    })
    const wrapper = mountBar()
    await flushPromises()
    expect(wrapper.find('.enterprise-update-bar').exists()).toBe(false)
  })

  it('dismisses bar when dismiss button is clicked', async () => {
    checkEnterpriseUpdates.mockResolvedValue({
      data: {
        flags: { needs_update: true },
        update_hub: { sha256: 'newsha', version: '1.0', git_sha: '' },
        enterprise: { deployed_sha256: 'old' },
      },
    })
    const wrapper = mountBar()
    await flushPromises()
    await wrapper.find('.enterprise-update-bar__dismiss').trigger('click')
    expect(wrapper.find('.enterprise-update-bar').exists()).toBe(false)
    expect(sessionStorage.getItem('xcagi_enterprise_update_dismiss_sha')).toBe('newsha')
  })

  it('opens modal when check and update button is clicked', async () => {
    checkEnterpriseUpdates.mockResolvedValue({
      data: {
        flags: { needs_update: true },
        update_hub: { sha256: 'newsha', version: '1.0', git_sha: '' },
        enterprise: { deployed_sha256: 'old' },
      },
    })
    const wrapper = mountBar()
    await flushPromises()
    expect(wrapper.find('.modal-stub').exists()).toBe(false)
    await wrapper.find('.btn-primary').trigger('click')
    expect(wrapper.find('.modal-stub').exists()).toBe(true)
  })

  it('shows check data in modal when available', async () => {
    checkEnterpriseUpdates.mockResolvedValue({
      data: {
        flags: { needs_update: true },
        update_hub: { sha256: 'newsha', version: '1.0', git_sha: 'abcdef' },
        enterprise: { deployed_sha256: 'oldsha123' },
      },
    })
    const wrapper = mountBar()
    await flushPromises()
    await wrapper.find('.btn-primary').trigger('click')
    expect(wrapper.find('.enterprise-update-table').exists()).toBe(true)
    expect(wrapper.text()).toContain('abcdef')
    expect(wrapper.text()).toContain('oldsha123')
  })

  it('applies update when runApply is triggered', async () => {
    checkEnterpriseUpdates.mockResolvedValue({
      data: {
        flags: { needs_update: true },
        update_hub: { sha256: 'newsha', version: '1.0', git_sha: '' },
        enterprise: { deployed_sha256: 'old' },
      },
    })
    applyEnterpriseUpdate.mockResolvedValue({
      data: { job_id: 'job1', steps: [{ id: 's1', label: '拉取', status: 'running' }] },
    })
    getEnterpriseJob.mockResolvedValue({
      data: { status: 'done', steps: [{ id: 's1', label: '拉取', status: 'done' }] },
    })
    const wrapper = mountBar()
    await flushPromises()
    await wrapper.find('.btn-primary').trigger('click')
    const applyBtn = wrapper.findAll('button').find((b) => b.text().includes('立即更新'))!
    await applyBtn.trigger('click')
    await flushPromises()
    expect(applyEnterpriseUpdate).toHaveBeenCalled()
  })

  it('shows job steps when polling returns them', async () => {
    vi.useFakeTimers()
    checkEnterpriseUpdates.mockResolvedValue({
      data: {
        flags: { needs_update: true },
        update_hub: { sha256: 'newsha', version: '1.0', git_sha: '' },
        enterprise: { deployed_sha256: 'old' },
      },
    })
    applyEnterpriseUpdate.mockResolvedValue({
      data: { job_id: 'job1', steps: [{ id: 's1', label: '拉取制品', status: 'running' }] },
    })
    getEnterpriseJob.mockResolvedValue({
      data: {
        status: 'running',
        steps: [
          { id: 's1', label: '拉取制品', status: 'done' },
          { id: 's2', label: '应用更新', status: 'running' },
        ],
      },
    })
    const wrapper = mountBar()
    await flushPromises()
    await wrapper.find('.btn-primary').trigger('click')
    const applyBtn = wrapper.findAll('button').find((b) => b.text().includes('立即更新'))!
    await applyBtn.trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1300)
    expect(wrapper.find('.enterprise-update-steps').exists()).toBe(true)
    expect(wrapper.text()).toContain('拉取制品')
    expect(wrapper.text()).toContain('应用更新')
  })

  it('shows error when applyEnterpriseUpdate throws', async () => {
    checkEnterpriseUpdates.mockResolvedValue({
      data: {
        flags: { needs_update: true },
        update_hub: { sha256: 'newsha', version: '1.0', git_sha: '' },
        enterprise: { deployed_sha256: 'old' },
      },
    })
    applyEnterpriseUpdate.mockRejectedValue(new Error('apply failed'))
    const wrapper = mountBar()
    await flushPromises()
    await wrapper.find('.btn-primary').trigger('click')
    const applyBtn = wrapper.findAll('button').find((b) => b.text().includes('立即更新'))!
    await applyBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.enterprise-update-error').text()).toContain('apply failed')
  })

  it('shows error when applyEnterpriseUpdate returns no job_id', async () => {
    checkEnterpriseUpdates.mockResolvedValue({
      data: {
        flags: { needs_update: true },
        update_hub: { sha256: 'newsha', version: '1.0', git_sha: '' },
        enterprise: { deployed_sha256: 'old' },
      },
    })
    applyEnterpriseUpdate.mockResolvedValue({ data: {}, message: '未收到任务' })
    const wrapper = mountBar()
    await flushPromises()
    await wrapper.find('.btn-primary').trigger('click')
    const applyBtn = wrapper.findAll('button').find((b) => b.text().includes('立即更新'))!
    await applyBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.enterprise-update-error').text()).toContain('未收到任务')
  })

  it('shows "更新中…" text when applying', async () => {
    checkEnterpriseUpdates.mockResolvedValue({
      data: {
        flags: { needs_update: true },
        update_hub: { sha256: 'newsha', version: '1.0', git_sha: '' },
        enterprise: { deployed_sha256: 'old' },
      },
    })
    let resolveApply: (v: unknown) => void
    applyEnterpriseUpdate.mockReturnValue(
      new Promise((resolve) => {
        resolveApply = resolve
      }),
    )
    const wrapper = mountBar()
    await flushPromises()
    await wrapper.find('.btn-primary').trigger('click')
    const applyBtn = wrapper.findAll('button').find((b) => b.text().includes('立即更新'))!
    await applyBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.enterprise-update-bar__text').text()).not.toBeUndefined()
    resolveApply!({ data: { job_id: 'j1', steps: [] } })
    await flushPromises()
  })

  it('renders hub version and sha in bar text', async () => {
    checkEnterpriseUpdates.mockResolvedValue({
      data: {
        flags: { needs_update: true },
        update_hub: { sha256: 'newsha', version: 'v2.0', git_sha: 'deadbeef' },
        enterprise: { deployed_sha256: 'old' },
      },
    })
    const wrapper = mountBar()
    await flushPromises()
    const text = wrapper.find('.enterprise-update-bar__text').text()
    expect(text).toContain('v2.0')
    expect(text).toContain('deadbeef')
  })

  it('renders bar without version/sha when not provided', async () => {
    checkEnterpriseUpdates.mockResolvedValue({
      data: {
        flags: { needs_update: true },
        update_hub: { sha256: 'newsha', version: '', git_sha: '' },
        enterprise: { deployed_sha256: 'old' },
      },
    })
    const wrapper = mountBar()
    await flushPromises()
    expect(wrapper.find('.enterprise-update-bar').exists()).toBe(true)
  })
})
