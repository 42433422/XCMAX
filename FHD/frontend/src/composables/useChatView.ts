import type { Ref } from 'vue'
import { useChatOrchestration } from './useChatOrchestration'

export interface UseChatViewOptions {
  sessionId: Ref<string>
  /** 当前会话是否有进行中的轮次；同步时用于判断本地未入库消息是否仍然有效。 */
  isBusy?: () => boolean
}

/** Facade: wires extracted composables; implementation in useChatOrchestration. */
export function useChatView(options: UseChatViewOptions) {
  return useChatOrchestration(options)
}
