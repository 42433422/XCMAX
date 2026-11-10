import { ref } from 'vue'

/** Model/chat dependency only. An unrelated health probe must not flip this. */
export const modelPathStatus = ref('unknown')

export function noteModelPath(status) {
  modelPathStatus.value = status === 'healthy' ? 'healthy' : 'degraded'
}

export function resetModelPath() {
  modelPathStatus.value = 'unknown'
}
