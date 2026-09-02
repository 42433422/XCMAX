/**
 * 面板开关（缺口 / 批量执行 / 员工大会 / 无密钥）与详情折叠。
 *
 * 由 AdminDutyEmployeeGraph.vue 原文机械迁出。
 */
import type { AdminDutyState } from './useAdminDutyState'
import type { AdminDutyNoKey } from './useAdminDutyNoKey'

export function useAdminDutyPanels(s: AdminDutyState, nokey: AdminDutyNoKey) {
  const { loadNoKeyEmployees } = nokey
  const { showGapPanel, showRunPanel, showAllHandsPanel, showNoKeyPanel, detailCollapsed } = s

  const closeOtherPanels = (except?: string) => {
    if (except !== 'gap') showGapPanel.value = false
    if (except !== 'run') showRunPanel.value = false
    if (except !== 'allhands') showAllHandsPanel.value = false
    if (except !== 'nokey') showNoKeyPanel.value = false
  }

  const togglePanel = (panel: 'gap' | 'run' | 'allhands' | 'nokey') => {
    const refs: Record<string, { value: boolean }> = {
      gap: showGapPanel,
      run: showRunPanel,
      allhands: showAllHandsPanel,
      nokey: showNoKeyPanel,
    }
    const isOpen = refs[panel].value
    closeOtherPanels(panel)
    refs[panel].value = !isOpen
    if (panel === 'nokey' && showNoKeyPanel.value) void loadNoKeyEmployees()
  }

  const openNoKeyPanel = () => togglePanel('nokey')

  const isDetailOpen = (key: string): boolean => detailCollapsed.value[key] !== true

  const toggleDetail = (key: string) => {
    detailCollapsed.value = { ...detailCollapsed.value, [key]: !detailCollapsed.value[key] }
  }

  return { closeOtherPanels, togglePanel, openNoKeyPanel, isDetailOpen, toggleDetail }
}

export type AdminDutyPanels = ReturnType<typeof useAdminDutyPanels>
