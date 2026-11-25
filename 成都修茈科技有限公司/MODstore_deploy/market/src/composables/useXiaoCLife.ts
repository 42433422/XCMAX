import { defineStore } from 'pinia'
import { onBeforeUnmount, ref, shallowRef, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { xiaocLifeApi, type XiaoCLifeChange, type XiaoCLifeState } from '../application/xiaocLifeApi'
import { ApiError } from '../infrastructure/http/client'

const useLifeStore = defineStore('xiaoc-enterprise-life', () => {
  const state = shallowRef<XiaoCLifeState | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const error = ref('')
  let actor: number | undefined
  let generation = 0
  let readSequence = 0
  let readers = 0
  let timer: ReturnType<typeof setInterval> | undefined
  let channel: BroadcastChannel | undefined
  let readInFlight: Promise<void> | undefined

  async function refresh(): Promise<void> {
    if (actor === undefined) return
    if (readInFlight) return readInFlight
    const epoch = generation
    const sequence = ++readSequence
    // Keep the previous failure visible until an authoritative read succeeds.
    loading.value = true
    const request = (async () => {
      try {
        const next = await xiaocLifeApi.read()
        if (epoch !== generation || sequence !== readSequence) return
        if (!state.value || next.identity_id !== state.value.identity_id || next.revision >= state.value.revision) {
          state.value = next
          error.value = ''
        }
      } catch (failure) {
        if (epoch !== generation || sequence !== readSequence) return
        const accessDenied = failure instanceof ApiError && (failure.status === 401 || failure.status === 403)
        if (accessDenied) state.value = null
        error.value = accessDenied ? '当前账号无法管理企业小 C。' : '暂时无法读取小 C 状态，请刷新重试。'
      } finally {
        if (epoch === generation && sequence === readSequence) loading.value = false
      }
    })()
    readInFlight = request
    await request
    if (readInFlight === request) readInFlight = undefined
  }

  function invalidate() {
    if (!saving.value && document.visibilityState !== 'hidden') void refresh()
  }

  function stop() {
    clearInterval(timer)
    timer = undefined
    channel?.close()
    channel = undefined
    window.removeEventListener('focus', invalidate)
    document.removeEventListener('visibilitychange', invalidate)
  }

  function connect(owner: number | undefined) {
    if (actor !== owner) {
      generation += 1
      readSequence += 1
      state.value = null
      loading.value = false
      saving.value = false
      error.value = ''
      readInFlight = undefined
      actor = owner
    }
    readers += 1
    if (owner !== undefined && !timer) {
      timer = setInterval(invalidate, 15_000)
      window.addEventListener('focus', invalidate)
      document.addEventListener('visibilitychange', invalidate)
      if (typeof BroadcastChannel !== 'undefined') {
        channel = new BroadcastChannel('xcmax-xiaoc-life')
        channel.onmessage = invalidate
      }
    }
    if (owner !== undefined) void refresh()
    else stop()
    return () => {
      readers -= 1
      if (readers === 0) {
        stop()
        generation += 1
        readSequence += 1
        actor = undefined
        state.value = null
        readInFlight = undefined
        loading.value = false
        saving.value = false
      }
    }
  }

  async function mutate(
    operation: (revision: number) => Promise<XiaoCLifeState>,
    expectedRevision = state.value?.revision,
  ): Promise<boolean> {
    if (actor === undefined || !state.value || saving.value || error.value || expectedRevision === undefined) return false
    const epoch = generation
    readSequence += 1
    readInFlight = undefined
    loading.value = false
    saving.value = true
    error.value = ''
    try {
      const next = await operation(expectedRevision)
      if (epoch !== generation) return false
      state.value = next
      channel?.postMessage('invalidate')
      return true
    } catch (failure) {
      if (epoch !== generation) return false
      const conflict = failure instanceof ApiError && failure.status === 409
      await refresh()
      if (epoch !== generation) return false
      error.value = conflict
        ? '企业设置已在其他窗口更新。已读取最新状态，请核对后再修改。'
        : failure instanceof ApiError && failure.status === 422
          ? '设置未通过校验，请检查预算、次数及授权到期时间。'
          : '暂时无法确认设置结果，请核对最新状态后重试。'
      return false
    } finally {
      if (epoch === generation) saving.value = false
    }
  }

  function save(change: XiaoCLifeChange, expectedRevision = state.value?.revision) {
    return mutate((revision) => xiaocLifeApi.update(revision, change), expectedRevision)
  }

  function promote(goalId: string) {
    const policy = state.value?.policy
    if (!policy?.portfolio_limits || !policy.employee_id) return Promise.resolve(false)
    const employeeId = policy.employee_id
    const limits = policy.portfolio_limits
    const inputData = policy.task_input ?? {}
    return mutate(async (revision) => (await xiaocLifeApi.promote(goalId, revision, employeeId, limits, inputData)).life)
  }

  return { state, loading, saving, error, connect, refresh, save, promote }
})

/** All management views read one server identity; owner only clears local state on account changes. */
export function useXiaoCLife(owner: MaybeRefOrGetter<number | undefined>) {
  const store = useLifeStore()
  let disconnect: (() => void) | undefined
  watch(
    () => toValue(owner),
    (value) => {
      disconnect?.()
      disconnect = store.connect(value)
    },
    { immediate: true },
  )
  onBeforeUnmount(() => disconnect?.())
  return store
}
