import { Blob as NodeBlob } from 'node:buffer'
import { createHash, webcrypto } from 'node:crypto'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '@/api/core'
import { downloadBlob } from '@/utils'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import AgentArtifactDownloads from './AgentArtifactDownloads.vue'

vi.mock('@/api/core', () => ({ api: { download: vi.fn() } }))
vi.mock('@/utils', () => ({ downloadBlob: vi.fn() }))
const id = 'a'.repeat(32)
const content = '客户,数量\n甲,3'
const blob = new NodeBlob([content], { type: 'text/csv' })
const receipt = () => ({ artifact_id: id, name: '客户.csv', uri: `/api/aiopen/artifacts/${id}`,
  metadata: { size: blob.size, sha256: createHash('sha256').update(content).digest('hex'), expires_at: Date.now() / 1000 + 3600, authenticated_download: true } })
const response = (body = blob) => ({ headers: new Headers(), blob: async () => body }) as unknown as Response
const wrappers: ReturnType<typeof mount>[] = []
function render(artifacts = [receipt()]) {
  const wrapper = mount(AgentArtifactDownloads, { props: { artifacts } })
  wrappers.push(wrapper)
  return wrapper
}
beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal('crypto', webcrypto) })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.unstubAllGlobals(); vi.useRealTimers() })

it('shows a direct file action and downloads verified bytes with the existing authenticated client', async () => {
  vi.mocked(api.download).mockResolvedValue(response())
  const wrapper = render()
  expect(wrapper.get('section').attributes('aria-label')).toBe('生成文件')
  expect(wrapper.text()).toContain('客户.csv')
  await wrapper.get('button').trigger('click')
  await vi.waitFor(() => expect(downloadBlob).toHaveBeenCalledWith(blob, '客户.csv'))
  expect(api.download).toHaveBeenCalledWith(`/api/aiopen/artifacts/${id}`, {}, { signal: expect.any(AbortSignal), redirect: 'error' })
  expect(wrapper.text()).toContain('下载已发起')
  expect(wrapper.text()).not.toContain('已保存')
})

it('hides unsupported paths and disables expired receipts before making a request', () => {
  const external = render([{ ...receipt(), uri: 'https://example.invalid/file' }])
  expect(external.find('button').exists()).toBe(false)
  const old = receipt()
  old.metadata.expires_at = 1
  const expired = render([old])
  expect(expired.get('button').attributes('disabled')).toBeDefined()
  expect(expired.text()).toContain('已过期')
  expect(api.download).not.toHaveBeenCalled()
})

it('reports a denied download and allows a deliberate retry', async () => {
  vi.mocked(api.download).mockRejectedValueOnce(new Error('文件已失效或无权访问')).mockResolvedValue(response())
  const wrapper = render()
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('无权访问')
  await wrapper.get('button').trigger('click')
  await vi.waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1))
})

it('refuses wrong-sized and same-sized corrupted content', async () => {
  const wrapper = render()
  vi.mocked(api.download).mockResolvedValueOnce(response(new NodeBlob(['short'])))
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('不完整')
  vi.mocked(api.download).mockResolvedValueOnce(response(new NodeBlob([new Uint8Array(blob.size)])))
  await wrapper.get('button').trigger('click')
  await vi.waitFor(() => expect(wrapper.get('[role="alert"]').text()).toContain('校验失败'))
  expect(downloadBlob).not.toHaveBeenCalled()
})

it('retires a pending download when the account changes, including A to B to A', async () => {
  let finish!: (value: Response) => void
  vi.mocked(api.download).mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const wrapper = render()
  await wrapper.get('button').trigger('click')
  const signal = vi.mocked(api.download).mock.calls[0]![2]!.signal!
  productReadAccountEpoch.value += 2
  expect(signal.aborted).toBe(true)
  finish(response()); await flushPromises()
  expect(downloadBlob).not.toHaveBeenCalled()
  expect(wrapper.text()).not.toContain('下载已发起')
})

it('keeps an identical receipt across polling but cancels when that receipt is removed', async () => {
  let finish!: (value: Response) => void
  vi.mocked(api.download).mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const item = receipt()
  const wrapper = render([item])
  await wrapper.get('button').trigger('click')
  const signal = vi.mocked(api.download).mock.calls[0]![2]!.signal!
  await wrapper.setProps({ artifacts: [JSON.parse(JSON.stringify(item))] })
  expect(signal.aborted).toBe(false)
  await wrapper.setProps({ artifacts: [] })
  expect(signal.aborted).toBe(true)
  finish(response()); await flushPromises()
  expect(downloadBlob).not.toHaveBeenCalled()
})

it('downloads the server-verified file on LAN pages without Web Crypto', async () => {
  vi.stubGlobal('crypto', {})
  const result = response()
  result.headers.set('X-Content-SHA256', receipt().metadata.sha256)
  vi.mocked(api.download).mockResolvedValue(result)
  const wrapper = render()
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(downloadBlob).toHaveBeenCalledWith(blob, '客户.csv')
})

it('disables duplicate requests and restores the button after a timeout', async () => {
  vi.useFakeTimers()
  vi.mocked(api.download).mockImplementation((_url, _params, options) => new Promise((_resolve, reject) => {
    options!.signal!.addEventListener('abort', () => reject(new Error('aborted')), { once: true })
  }))
  const wrapper = render()
  await wrapper.get('button').trigger('click')
  expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  await wrapper.get('button').trigger('click')
  expect(api.download).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(90_000)
  expect(wrapper.get('[role="alert"]').text()).toContain('超时')
  expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
})
