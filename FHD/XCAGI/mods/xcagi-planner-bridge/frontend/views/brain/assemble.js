import { onMounted, onUnmounted, ref } from 'vue'
import {
  XCAGI_AI_TIER_CHANGED_EVENT
} from '@/utils/xcagiStorageKeys'
import { useBrainActivity } from './useBrainActivity'
import { useBrainAgentChat } from './useBrainAgentChat'
import { useBrainTier } from './useBrainTier'
import { useBrainOpenapi } from './useBrainOpenapi'
import { useBrainCodeEditor } from './useBrainCodeEditor'
import { useBrainModels } from './useBrainModels'
import { useBrainPane } from './useBrainPane'
import { tabs, architectureDiagram, skillRows } from './brainStatic'

/**
 * 组装智脑视图全部状态与动作；子组件通过单一 ctx prop 共享，
 * 逻辑自 BrainView.vue 逐字迁移，行为不变。
 */
export function assembleBrainView() {
  const activeTab = ref('architecture')
  const activity = useBrainActivity()
  const agentChat = useBrainAgentChat({ pushActivity: activity.pushActivity })
  const tier = useBrainTier({ pushActivity: activity.pushActivity })
  const openapi = useBrainOpenapi({ pushActivity: activity.pushActivity })
  const codeEditor = useBrainCodeEditor({ pushActivity: activity.pushActivity })
  const models = useBrainModels({ pushActivity: activity.pushActivity })
  const pane = useBrainPane()

  onMounted(() => {
    void agentChat.initBrainAgentSession()
    activity.activityLines.value = []
    activity.pushActivity('智脑控制台已就绪')
    pane.bindBrainPaneViewport()
    window.addEventListener('storage', tier.onStorage)
    window.addEventListener('focus', tier.onWindowFocus)
    window.addEventListener(XCAGI_AI_TIER_CHANGED_EVENT, tier.onAiTierChanged)
    tier.loadTierStatus().then(() => {
      if (tier.tierStatus.value) {
        activity.pushActivity('已同步 /api/fhd/ai-tier/status')
      }
    })
    models.loadPublicModels()
    openapi.loadOpenapi()
  })

  onUnmounted(() => {
    pane.unbindBrainPaneViewport()
    window.removeEventListener('storage', tier.onStorage)
    window.removeEventListener('focus', tier.onWindowFocus)
    window.removeEventListener(XCAGI_AI_TIER_CHANGED_EVENT, tier.onAiTierChanged)
  })

  return {
    tabs,
    architectureDiagram,
    skillRows,
    activeTab,
    ...activity,
    ...agentChat,
    ...tier,
    ...openapi,
    ...codeEditor,
    ...models,
    ...pane,
  }
}
