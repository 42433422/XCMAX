import { ref } from 'vue'

/** Model/chat dependency only. An unrelated health probe must not flip this. */
export const modelPathStatus = ref<'unknown' | 'healthy' | 'degraded'>('unknown')

export function noteModelPath(status: 'healthy' | 'degraded') {
  modelPathStatus.value = status === 'healthy' ? 'healthy' : 'degraded'
}

export function resetModelPath() {
  modelPathStatus.value = 'unknown'
}
