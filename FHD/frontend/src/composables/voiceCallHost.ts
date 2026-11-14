/** 语音通话宿主：通话界面固定在小C悬浮窗内，不再单独占一页。 */
import { ref, shallowRef, type Ref } from 'vue'
import type { ChatMessage } from './useChatMessages'

/** 通话进行中时，主框架要保留小C悬浮窗，保证静音/挂断始终可见。 */
export const voiceCallActive = ref(false)

/**
 * 智能对话页把自身的会话消息与发送函数登记到这里，通话轮直接写进同一份对话。
 * 用单对象 shallowRef 承载注册项：悬浮窗可能先于对话页挂载，注册发生时必须能触发订阅方更新。
 */
export interface VoiceChatBridge {
  messages: Ref<ChatMessage[]> | null
  send: ((text: string) => Promise<void>) | null
  isLoading: Ref<boolean> | null
}

export const voiceChatBridge = shallowRef<VoiceChatBridge>({
  messages: null,
  send: null,
  isLoading: null,
})

/** 其它页面（如智能对话输入框）只发起点话，界面与通话状态都由悬浮窗承载。 */
export function requestVoiceCallStart(options: { expandPanel?: boolean } = {}): void {
  window.dispatchEvent(
    new CustomEvent('xcagi:start-voice-call', { detail: { expandPanel: options.expandPanel !== false } }),
  )
}
