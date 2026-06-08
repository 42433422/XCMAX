import type { InjectionKey } from 'vue'

export type AgentHandleInputFn = (
  userText: string,
  opts?: { withScreenshot?: boolean },
) => Promise<void>

export const AGENT_HANDLE_INPUT_KEY: InjectionKey<AgentHandleInputFn> = Symbol('agentHandleInput')

export const AGENT_CORP_MODE_KEY: InjectionKey<boolean> = Symbol('agentCorpMode')
