import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import Panel from '../../../admin-console/src/components/workflow/RetortEvolutionPanel.vue'

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/api/core', () => ({
  default: mocks,
  ApiError: class extends Error {
    status = 0
  },
}))
const run = () => ({
  id: 'run-1',
  status: 'awaiting_dispatch_approval',
  error: '',
  protocol: {
    title: '恢复验证',
    goal: '中断后恢复任务',
    repository: 'example/product',
    source_sha: 'a'.repeat(40),
    criterion_ids: ['shared-engine-B2'],
    criteria: [{ id: 'shared-engine-B2', domain_name: 'Retort 共享引擎', requirement: '恢复不重复派工' }],
  },
  snapshot: { pending: [{ kind: 'dispatch_approval', digest: 'b'.repeat(64) }], plan: { public_body: '将公开的任务内容' } },
  effects: {},
})
const overview = () => ({
  items: [run()],
  total: 12,
  standard_version: '1',
  domains: Array.from({ length: 18 }, (_, i) => ({ id: `domain-${i}`, name: `能力域 ${i}`, criteria: [] })),
  templates: [],
  connections: { checkpoint: false, github: true, employees: false, protocols: false },
})
let wrapper: VueWrapper
beforeEach(() => {
  mocks.get.mockReset().mockImplementation((url: string) => Promise.resolve(url.endsWith('run-1') ? run() : overview()))
  mocks.post.mockReset().mockResolvedValue({})
})
afterEach(() => {
  wrapper?.unmount()
  document.body.replaceChildren()
})
function render() {
  wrapper = mount(Panel, { attachTo: document.body })
  return wrapper
}

describe('Retort native approval console', () => {
  it('shows missing connections and keeps the list paginated', async () => {
    render()
    await flushPromises()
    expect(wrapper.text()).toContain('18 域 · 12 个改进任务')
    expect(wrapper.text()).toContain('待接通：持久存储、云端员工、验收方案')
    const create = wrapper.findAll('button').find((b) => b.text() === '新建改进任务')!
    expect(create.attributes('disabled')).toBeDefined()
    await wrapper.get('button[aria-label="Go to next page"]').trigger('click')
    await flushPromises()
    expect(mocks.get).toHaveBeenLastCalledWith('/api/xcmax/admin/retort-evolution', { offset: 8, limit: 8 })
  })
  it('previews the public issue and binds approval to the displayed evidence', async () => {
    const detail = run()
    const feedback = { ...detail, snapshot: { ...detail.snapshot, plan: {
      public_body: detail.snapshot.plan.public_body,
      private_customer_feedback: { reproduction: ['首次导入未成功 <script>untrusted()</script>'] },
    } } }
    mocks.get.mockImplementation((url: string) => Promise.resolve(url.endsWith('run-1') ? feedback : overview()))
    render()
    await flushPromises()
    await wrapper.get('.el-table__body button').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('将公开的任务内容')
    expect(document.body.textContent).toContain('首次导入未成功 <script>untrusted()</script>')
    expect(document.body.querySelector('script')).toBeNull()
    expect(document.body.textContent).toContain('未评级')
    const approve = [...document.body.querySelectorAll('button')].find((b) => b.textContent?.includes('批准并派工'))!
    approve.click()
    await flushPromises()
    expect(mocks.post).toHaveBeenCalledWith('/api/xcmax/admin/retort-evolution/run-1/decision', { digest: 'b'.repeat(64), approved: true })
    expect(mocks.post.mock.calls[0][1]).not.toHaveProperty('actor_id')
  })
  it('keeps a failed approval visible without claiming completion', async () => {
    mocks.post.mockRejectedValue(new Error('审批内容已变化，请刷新证据'))
    render()
    await flushPromises()
    await wrapper.get('.el-table__body button').trigger('click')
    await flushPromises()
    ;[...document.body.querySelectorAll('button')].find((b) => b.textContent?.includes('批准并派工'))!.click()
    await flushPromises()
    expect(document.body.textContent).toContain('审批内容已变化，请刷新证据')
    expect(document.body.textContent).not.toContain('已归档验收结果')
  })
  it('requires separate acceptance after independent checks', async () => {
    const detail = run()
    detail.status = 'awaiting_acceptance'
    detail.snapshot.pending = [{ kind: 'acceptance', digest: 'c'.repeat(64) }]
    mocks.get.mockImplementation((url: string) => Promise.resolve(url.endsWith('run-1') ? detail : overview()))
    render()
    await flushPromises()
    await wrapper.get('.el-table__body button').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('独立检查已通过，等待确认实际任务效果')
    expect(document.body.textContent).not.toContain('批准并派工')
    ;[...document.body.querySelectorAll('button')].find((b) => b.textContent?.includes('确认验收'))!.click()
    await flushPromises()
    expect(mocks.post).toHaveBeenCalledWith('/api/xcmax/admin/retort-evolution/run-1/decision', { digest: 'c'.repeat(64), approved: true })
  })
  it('shows the credential pause without offering approval as an execution bypass', async () => {
    const detail = {
      ...run(), status: 'waiting_credential_isolation',
      snapshot: { pending: [{ kind: 'execution' }], execution: {
        reason: 'customer_feedback_requires_non_exportable_model_credentials',
      } },
    }
    mocks.get.mockImplementation((url: string) => Promise.resolve(url.endsWith('run-1') ? detail : overview()))
    render()
    await flushPromises()
    await wrapper.get('.el-table__body button').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('等待凭据隔离')
    expect(document.body.textContent).toContain('客户反馈修复已暂停')
    expect([...document.body.querySelectorAll('button')].some((b) => b.textContent?.includes('批准并派工'))).toBe(false)
    expect(mocks.post).not.toHaveBeenCalled()
  })
  it('shows the merged repair and verified running release as distinct revisions', async () => {
    const merge = 'c'.repeat(40)
    const release = 'd'.repeat(40)
    const detail = {
      ...run(),
      status: 'completed',
      snapshot: {
        delivery: {
          status: 'deployment_verified',
          merge_sha: merge,
          release_sha: release,
          identity: { product_version: '1.0.0.7' },
          url: 'https://github.com/example/product/actions/runs/42',
        },
      },
    }
    mocks.get.mockImplementation((url: string) => Promise.resolve(url.endsWith('run-1') ? detail : overview()))
    render()
    await flushPromises()
    await wrapper.get('.el-table__body button').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain(merge)
    expect(document.body.textContent).toContain(release)
    expect(document.body.textContent).toContain('1.0.0.7')
    expect(document.body.textContent).toContain('正式发布验收记录')
  })
})
