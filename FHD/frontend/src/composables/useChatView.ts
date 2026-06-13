import type { Ref } from 'vue'
import { useChatOrchestration } from './useChatOrchestration'

export interface UseChatViewOptions {
  sessionId: Ref<string>
  proIntentExperienceEnabled?: Ref<boolean>
}

/** Facade: wires extracted composables; implementation in useChatOrchestration. */
export function useChatView(options: UseChatViewOptions) {
  return useChatOrchestration(options)
}
