import { createHash } from 'node:crypto'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import agentRunsApi from '@/api/agentRuns'
import * as downloads from '@/utils'
import { readAgentArtifactDownloads } from '@/utils/agentArtifactDownloads'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import AgentArtifactDownloadList from './AgentArtifactDownloadList.vue'

enableAutoUnmount(afterEach)
const content = 'verified result'
const checksum = (bytes: string) => createHash('sha256').update(bytes).digest('hex')
const file = {
  run_id: 'run-child', artifact_id: 'xlsx_verified', artifact_type: 'file' as const,
  name: 'result.xlsx', uri: '/api/agent/runs/run-child/artifacts/xlsx_verified',
  metadata: { sha256: checksum(content), size_bytes: content.length },
}
function response(bytes = content): Response {
  return new Response(bytes, { headers: {
    'Content-Type': 'application/octet-stream',
    'X-Artifact-SHA256': checksum(bytes), 'X-Artifact-Size': String(bytes.length),
  } })
}

describe('verified artifact delivery', () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('retains the verified checksum and byte count through the file projection', () => {
    expect(readAgentArtifactDownloads([file])).toEqual([file])
  })

  it('does not silently overwrite the expected run or malformed integrity metadata', () => {
    expect(readAgentArtifactDownloads([{ ...file, run_id: 'different' }], 'run-child')).toEqual([])
    expect(readAgentArtifactDownloads([{ ...file, metadata: { sha256: 'invalid' } }])).toEqual([])
    expect(readAgentArtifactDownloads([{ ...file, metadata: { ...file.metadata, size_bytes: -1 } }])).toEqual([])
  })

  it('saves only the bytes matching the original receipt', async () => {
    const download = vi.spyOn(agentRunsApi, 'downloadArtifact').mockResolvedValue(response())
    const save = vi.spyOn(downloads, 'downloadBlob').mockImplementation(() => {})
    const wrapper = mount(AgentArtifactDownloadList, { props: { files: [file], scope: 'turn-1' } })
    await wrapper.get('button').trigger('click')
    await vi.waitFor(() => expect(save).toHaveBeenCalledOnce())
    expect(download).toHaveBeenCalledExactlyOnceWith(file.run_id, file.artifact_id)
    expect(save.mock.calls[0]?.[0].size).toBe(content.length)
    expect(save.mock.calls[0]?.[1]).toBe(file.name)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it.each(['changed bytes', 'wrong size', 'wrong transport digest', 'missing digest'])('rejects %s before creating a download', async failure => {
    const selected = failure === 'missing digest' ? { ...file, metadata: undefined }
      : failure === 'wrong size' ? { ...file, metadata: { ...file.metadata, size_bytes: 1 } } : file
    const reply = response(failure === 'changed bytes' ? 'changed result' : content)
    if (failure === 'wrong transport digest') reply.headers.set('X-Artifact-SHA256', 'invalid')
    if (failure === 'missing digest') reply.headers.delete('X-Artifact-SHA256')
    vi.spyOn(agentRunsApi, 'downloadArtifact').mockResolvedValue(reply)
    const save = vi.spyOn(downloads, 'downloadBlob').mockImplementation(() => {})
    const wrapper = mount(AgentArtifactDownloadList, { props: { files: [selected], scope: 'turn-1' } })
    await wrapper.get('button').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('[role="alert"]').exists()).toBe(true))
    expect(save).not.toHaveBeenCalled()
  })

  it('validates an older history row against the current server checksum', async () => {
    vi.spyOn(agentRunsApi, 'downloadArtifact').mockResolvedValue(response())
    const save = vi.spyOn(downloads, 'downloadBlob').mockImplementation(() => {})
    const wrapper = mount(AgentArtifactDownloadList, { props: { files: [{ ...file, metadata: undefined }], scope: 'turn-1' } })
    await wrapper.get('button').trigger('click')
    await vi.waitFor(() => expect(save).toHaveBeenCalledOnce())
  })

  it.each([content, 'changed result'])('checks LAN HTTP bytes without WebCrypto: %s', async bytes => {
    vi.stubGlobal('crypto', undefined)
    vi.spyOn(agentRunsApi, 'downloadArtifact').mockResolvedValue(response(bytes))
    const save = vi.spyOn(downloads, 'downloadBlob').mockImplementation(() => {})
    const wrapper = mount(AgentArtifactDownloadList, { props: { files: [file], scope: 'turn-1' } })
    await wrapper.get('button').trigger('click')
    if (bytes === content) {
      await vi.waitFor(() => expect(save).toHaveBeenCalledOnce())
      expect(save.mock.calls[0]?.[0].size).toBe(content.length)
    } else {
      await vi.waitFor(() => expect(wrapper.find('[role="alert"]').exists()).toBe(true))
      expect(save).not.toHaveBeenCalled()
    }
  })

  it.each(['account', 'receipt', 'unmount'])('discards an in-flight download after %s changes', async change => {
    let resolve!: (reply: Response) => void
    vi.spyOn(agentRunsApi, 'downloadArtifact').mockReturnValue(new Promise(done => { resolve = done }))
    const save = vi.spyOn(downloads, 'downloadBlob').mockImplementation(() => {})
    const wrapper = mount(AgentArtifactDownloadList, { props: { files: [file], scope: 'turn-1' } })
    await wrapper.get('button').trigger('click')
    if (change === 'account') updateProductReadAccountScope({ localUserId: 'another-owner' })
    if (change === 'receipt') await wrapper.setProps({ files: [{ ...file, metadata: { ...file.metadata, sha256: checksum('changed') } }] })
    if (change === 'unmount') wrapper.unmount()
    resolve(response())
    await flushPromises()
    expect(save).not.toHaveBeenCalled()
  })
})
