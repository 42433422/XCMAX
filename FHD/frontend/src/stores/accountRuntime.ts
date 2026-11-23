import { computed, onScopeDispose, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/core'
import { PLATFORM_MODEL_CHANGED_EVENT, PLATFORM_MODEL_CHANGED_KEY } from '@/api/platformModel'
import { captureAuthSession, getAuthSessionEpoch } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { useAccountProfileStore } from './accountProfile'

type Qualification = 'passed' | 'required' | 'failed' | 'interrupted' | 'in_progress' | 'blocked'
interface RuntimeStatus {
  success: boolean
  qualification: Qualification
  managed_by: 'account' | 'deployment'
  route?: { model?: string; route_identity?: string }
  message?: string
  error_code?: string
  checks?: Record<string, 'PASS' | 'FAIL'>
}
type ReadMode = 'read' | 'retry'
const path = '/api/desktop/agent-runtime/qualification'
const states = new Set<Qualification>(['passed', 'required', 'failed', 'interrupted', 'in_progress', 'blocked'])
const unavailable = '运行状态未能确认，请检查登录状态、模型配置和本机运行环境后重试。'

function statusPayload(value: unknown): RuntimeStatus {
  const data = value as RuntimeStatus | null
  if (!data || !states.has(data.qualification) || !['account', 'deployment'].includes(data.managed_by) ||
    (data.success !== true && !(data.success === false && data.qualification === 'blocked')) ||
    (data.qualification === 'passed' && (typeof data.route?.route_identity !== 'string' || !data.route.route_identity.trim()))) throw new Error('Invalid runtime status')
  return data
}

function failureMessage(error: unknown): string {
  const data = (error as { data?: RuntimeStatus } | null)?.data
  return typeof data?.error_code === 'string' && data.error_code.startsWith('runtime_') && typeof data.message === 'string'
    ? data.message : unavailable
}

// This is a read-through view of the server's qualification, never a saved readiness flag.
// Lifecycle events only read; a shared operation may post only after an explicit user check.
export const useAccountRuntimeStore = defineStore('accountRuntime', () => {
  const account = useAccountProfileStore()
  const status = ref<RuntimeStatus | null>(null)
  const loading = ref(false), checking = ref(false), errorMessage = ref('')
  let started = false, generation = 0, polls = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let operation: { controller: AbortController; mode: ReadMode; promise?: Promise<void> } | null = null
  const eligible = () => account.workspaceReady && account.workspaceHydrationReady &&
    account.localUserId != null && !account.isImpersonating
  const busy = computed(() => loading.value || checking.value || status.value?.qualification === 'in_progress')
  const failed = computed(() => !!errorMessage.value || ['failed', 'interrupted', 'blocked'].includes(status.value?.qualification || ''))
  const message = computed(() => {
    if (checking.value) return '正在验收当前账号的模型与本机执行器，首次验收可能需要数分钟。'
    if (loading.value) return '正在读取当前账号的运行状态…'
    if (errorMessage.value) return errorMessage.value
    if (!status.value) return ''
    if (status.value.qualification === 'passed') {
      return `当前配置的运行验收已通过${status.value.route?.model ? `（${status.value.route.model}）` : ''}。`
    }
    if (status.value.message) return status.value.message
    return {
      required: '当前配置尚未完成运行验收。',
      failed: '运行验收未通过，修复模型配置或本机环境后可重新验收。',
      interrupted: '上次运行验收被中断，请核对后重新验收。',
      in_progress: '当前账号正在运行验收，完成后会自动更新状态。',
      blocked: '运行条件尚未就绪，请核对模型配置和本机环境。',
    }[status.value.qualification]
  })

  function invalidate() {
    generation++
    clearTimeout(timer); timer = undefined; polls = 0
    operation?.controller.abort()
    operation = null
    status.value = null
    loading.value = checking.value = false
    errorMessage.value = ''
  }

  function read(mode: ReadMode, polling = false): Promise<void> {
    if (!eligible()) return Promise.resolve()
    if (operation) {
      if (mode === 'retry') operation.mode = mode
      return operation.promise!
    }
    clearTimeout(timer); timer = undefined
    if (!polling) polls = 0
    const owner = generation, sameAccount = captureAuthSession()
    const request = { controller: new AbortController(), mode, promise: undefined as Promise<void> | undefined }
    operation = request
    const current = () => owner === generation && operation === request && sameAccount() && !account.isImpersonating
    status.value = null
    errorMessage.value = ''
    loading.value = true
    const readStatus = async () => {
      let result: RuntimeStatus
      try {
        result = statusPayload(await api.get(path, {}, { signal: request.controller.signal, timeoutMs: 30_000, cache: 'no-store', retry: false, quiet: true }))
      } catch (error) {
        const failure = error as { status?: number; data?: unknown }
        if (failure.status !== 409) throw error
        result = statusPayload(failure.data)
      }
      if (current()) status.value = result
      return result
    }
    request.promise = (async () => {
      try {
        const initial = await readStatus()
        if (!current()) return
        const needsAttempt = ['required', 'failed', 'interrupted'].includes(initial.qualification)
        if (request.mode === 'retry' && initial.managed_by === 'account' && needsAttempt) {
          loading.value = false
          checking.value = true
          let postFailure = ''
          try {
            await api.post(path, { retry: true }, { signal: request.controller.signal, timeoutMs: 600_000, retry: false, quiet: true })
          } catch (error) { postFailure = failureMessage(error) }
          if (!current()) return
          // Read the persisted result even after a lost POST response. It may be
          // in progress or complete; neither state permits another automatic POST.
          const confirmed = await readStatus()
          if (current() && postFailure && confirmed.qualification === 'required') errorMessage.value = postFailure
        }
      } catch (error) {
        if (current()) { status.value = null; errorMessage.value = failureMessage(error) }
      } finally {
        if (current()) {
          operation = null
          loading.value = checking.value = false
          if (started && status.value?.qualification === 'in_progress' && ++polls <= 120) {
            timer = setTimeout(() => { void read('read', true) }, 5_000)
          }
        }
      }
    })()
    return request.promise
  }

  const refresh = () => read('read')
  const retry = () => read('retry')
  const start = () => { started = true; return read('read') }
  function stop() { started = false; invalidate() }
  function modelChanged() { invalidate(); if (started) void read('read') }
  const storageChanged = (event: StorageEvent) => { if (event.key === PLATFORM_MODEL_CHANGED_KEY) modelChanged() }
  watch(() => [getAuthSessionEpoch(), productReadAccountEpoch.value, account.localUserId, account.isImpersonating], modelChanged, { flush: 'sync' })
  watch(() => account.workspaceReady && account.workspaceHydrationReady, ready => {
    if (ready && started && !status.value) void read('read')
  })
  window.addEventListener(PLATFORM_MODEL_CHANGED_EVENT, modelChanged)
  window.addEventListener('storage', storageChanged)
  onScopeDispose(() => {
    stop()
    window.removeEventListener(PLATFORM_MODEL_CHANGED_EVENT, modelChanged)
    window.removeEventListener('storage', storageChanged)
  })
  return { status, loading, checking, busy, failed, message, refresh, retry, start, stop, invalidate }
})
