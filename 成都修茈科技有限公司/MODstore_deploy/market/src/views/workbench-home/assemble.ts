// WorkbenchHomeView 拆分后的装配入口：顺序执行各分片并累积上下文（行为与原 setup 一致）。
import { useWbSuggestModIdFromText } from './useWbSuggestModIdFromText'
import { useWbDrawDirectWaveform } from './useWbDrawDirectWaveform'
import { useWbBuildDirectAttachItem } from './useWbBuildDirectAttachItem'
import { useWbLoadDirectEmployeeOptions } from './useWbLoadDirectEmployeeOptions'
import { useWbLoadWorkbenchRepoPicks } from './useWbLoadWorkbenchRepoPicks'
import { useWbRestoreMakeProgressCache } from './useWbRestoreMakeProgressCache'
import { useWbFlushPlanMermaidDiagrams } from './useWbFlushPlanMermaidDiagrams'
import { useWbRetrieveKnowledgeForDirect } from './useWbRetrieveKnowledgeForDirect'
import { useWbResolveChatProviderModel } from './useWbResolveChatProviderModel'
import { useWbRunDirectChatTurn } from './useWbRunDirectChatTurn'
import { useWbSendDirectChat } from './useWbSendDirectChat'
import { useWbConfirmPlanAndOpenHandoff } from './useWbConfirmPlanAndOpenHandoff'
import { useWbDispatchEmployeeVoiceUtterance } from './useWbDispatchEmployeeVoiceUtterance'
import { useWbDrawWaveform } from './useWbDrawWaveform'
import { useWbHandleVoicePlanReplySmart } from './useWbHandleVoicePlanReplySmart'
import { useWbHandleModeSwitchFromSidebar } from './useWbHandleModeSwitchFromSidebar'
import { useWbRunOrchestration } from './useWbRunOrchestration'
import { useWbOnInlineHoldEnd } from './useWbOnInlineHoldEnd'

export function assembleWorkbenchHome() {
  const c01 = useWbSuggestModIdFromText()
  const c02 = useWbDrawDirectWaveform(c01)
  const c03 = useWbBuildDirectAttachItem(c02)
  const c04 = useWbLoadDirectEmployeeOptions(c03)
  const c05 = useWbLoadWorkbenchRepoPicks(c04)
  const c06 = useWbRestoreMakeProgressCache(c05)
  const c07 = useWbFlushPlanMermaidDiagrams(c06)
  const c08 = useWbRetrieveKnowledgeForDirect(c07)
  const c09 = useWbResolveChatProviderModel(c08)
  const c10 = useWbRunDirectChatTurn(c09)
  const c11 = useWbSendDirectChat(c10)
  const c12 = useWbConfirmPlanAndOpenHandoff(c11)
  const c13 = useWbDispatchEmployeeVoiceUtterance(c12)
  const c14 = useWbDrawWaveform(c13)
  const c15 = useWbHandleVoicePlanReplySmart(c14)
  const c16 = useWbHandleModeSwitchFromSidebar(c15)
  const c17 = useWbRunOrchestration(c16)
  const c18 = useWbOnInlineHoldEnd(c17)
  return c18
}

export type WorkbenchHomeCtx = ReturnType<typeof assembleWorkbenchHome>
