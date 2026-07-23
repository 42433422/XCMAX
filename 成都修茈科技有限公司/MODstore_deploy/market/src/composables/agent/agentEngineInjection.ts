import type { InjectionKey } from 'vue'

export type AgentHandleInputFn = (
  userText: string,
  opts?: {
    withScreenshot?: boolean
    /** 用户本地上传的图片 data URL（优先于页面截图） */
    imageDataUrl?: string | null
    skipUserInsert?: boolean
  },
) => Promise<void>

export const AGENT_HANDLE_INPUT_KEY: InjectionKey<AgentHandleInputFn> = Symbol('agentHandleInput')

export const AGENT_CORP_MODE_KEY: InjectionKey<boolean> = Symbol('agentCorpMode')
