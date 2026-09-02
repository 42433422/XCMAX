// WorkbenchHomeView 拆分：前向 slot 单例（原文件内函数声明提升的跨片等价物）。
import type { useWbHandleVoicePlanReplySmart } from './useWbHandleVoicePlanReplySmart'
import type { useWbRunOrchestration } from './useWbRunOrchestration'

export const wbLate1 = Object.create(null) as Pick<ReturnType<typeof useWbHandleVoicePlanReplySmart>, 'handleVoicePlanReply' | 'handleVoicePlanReplySmart' | 'injectVoiceDuringWork' | 'runVoiceChatTurn' | 'runVoiceS2STurn' | 'runVoiceUnifiedTurn' | 'speakVoiceShort'> & Pick<ReturnType<typeof useWbRunOrchestration>, 'runOrchestration'>
