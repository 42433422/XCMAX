import { useChatDebugSim } from './useChatDebugSim'
import { useTestPack } from './useTestPack'

/**
 * 组装聊天调试工作台全部状态与动作；子组件通过单一 ctx prop 共享，
 * 逻辑自 ChatDebugView.vue 逐字迁移，行为不变。
 */
export function assembleChatDebug() {
  const sim = useChatDebugSim()
  const testPack = useTestPack({ inputText: sim.inputText })

  return {
    ...sim,
    ...testPack,
  }
}

export default assembleChatDebug
