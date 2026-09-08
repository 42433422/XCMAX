import { onScopeDispose, reactive, watch } from 'vue'
import type { AgentArtifact } from '@/api/agentRuns'
import { api } from '@/api/core'
import { downloadBlob } from '@/utils'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

const PRIVATE_EXPORT = /^\/api\/aiopen\/artifacts\/([a-f0-9]{32})$/
const MAX_BYTES = 64 * 1024 * 1024

export function downloadableArtifact(artifact: AgentArtifact): boolean {
  const match = PRIVATE_EXPORT.exec(artifact.uri || '')
  return Boolean(match && match[1] === artifact.artifact_id && artifact.metadata?.authenticated_download === true)
}

export function artifactExpired(artifact: AgentArtifact): boolean {
  const expiry = artifact.metadata?.expires_at
  return typeof expiry !== 'number' || !Number.isFinite(expiry) || expiry * 1000 <= Date.now()
}

export function useAgentArtifactDownloads() {
  const states = reactive<Record<string, { busy: boolean; message: string; failed: boolean }>>({})
  const pending = new Map<string, AbortController>()
  const clear = () => {
    for (const controller of pending.values()) controller.abort()
    pending.clear()
    for (const key of Object.keys(states)) delete states[key]
  }
  const stop = watch(productReadAccountEpoch, clear, { flush: 'sync' })
  onScopeDispose(() => { clear(); stop() })

  async function download(artifact: AgentArtifact): Promise<void> {
    const id = artifact.artifact_id
    if (pending.has(id)) return
    states[id] = { busy: true, message: '', failed: false }
    const state = states[id]
    const epoch = productReadAccountEpoch.value
    const controller = new AbortController()
    pending.set(id, controller)
    const timer = window.setTimeout(() => controller.abort(), 90_000)
    const current = () => {
      if (controller.signal.aborted || productReadAccountEpoch.value !== epoch) throw new Error('下载已取消，请在当前账号下重试')
    }
    try {
      const size = artifact.metadata?.size
      const digest = artifact.metadata?.sha256
      if (!downloadableArtifact(artifact)) throw new Error('该文件没有可用的下载回执')
      if (artifactExpired(artifact)) throw new Error('文件已过期，请重新生成')
      if (typeof size !== 'number' || !Number.isSafeInteger(size) || size < 0 || size > MAX_BYTES || typeof digest !== 'string' || !/^[a-f0-9]{64}$/.test(digest)) {
        throw new Error('文件回执不完整，请重新生成')
      }
      const response = await api.download(artifact.uri!, {}, { signal: controller.signal, redirect: 'error' })
      current()
      const serverDigest = response.headers.get('X-Content-SHA256')
      if (serverDigest && serverDigest !== digest) throw new Error('文件校验失败，请重新生成')
      const blob = await response.blob()
      current()
      if (blob.size !== size) throw new Error('文件内容不完整，请重试下载')
      // LAN HTTP can lack Web Crypto. The authenticated server always validates
      // the stored hash; secure origins additionally verify the received bytes.
      if (globalThis.crypto?.subtle) {
        const bytes = await blob.arrayBuffer()
        const hash = await crypto.subtle.digest('SHA-256', bytes)
        const actual = Array.from(new Uint8Array(hash), value => value.toString(16).padStart(2, '0')).join('')
        if (actual !== digest) throw new Error('文件校验失败，请重新生成')
      }
      current()
      const baseName = (artifact.name || 'export.bin').split(/[\\/]/).pop() || ''
      const filename = Array.from(baseName).filter(character => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127).join('') || 'export.bin'
      downloadBlob(blob, filename)
      state.message = '下载已发起'
    } catch (error) {
      if (productReadAccountEpoch.value === epoch && !controller.signal.aborted) {
        state.failed = true
        state.message = error instanceof Error ? error.message : '下载失败，请重试'
      } else if (productReadAccountEpoch.value === epoch && pending.get(id) === controller) {
        state.failed = true
        state.message = '下载超时或已取消，请重试'
      }
    } finally {
      window.clearTimeout(timer)
      if (pending.get(id) === controller) pending.delete(id)
      state.busy = false
    }
  }
  return { states, download, clear }
}
