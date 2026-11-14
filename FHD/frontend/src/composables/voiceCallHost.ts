/** 语音通话宿主：通话界面固定在小C悬浮窗内，不再单独占一页。 */
import { ref } from 'vue'

/** 通话进行中时，主框架要保留小C悬浮窗，保证静音/挂断始终可见。 */
export const voiceCallActive = ref(false)

/** 其它页面（如智能对话输入框）只发起点话，界面与通话状态都由悬浮窗承载。 */
export function requestVoiceCallStart(): void {
  window.dispatchEvent(new CustomEvent('xcagi:start-voice-call'))
}
