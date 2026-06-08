import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { AgentMessage, ButlerMode, OrchestrationSession, PendingAction } from '../types/agent'

const STORAGE_KEYS = {
  consent: 'xc_butler_consent',
  pos: 'xc_butler_pos',
  dismissed: 'xc_butler_dismissed',
}

function loadConsent(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEYS.consent) === 'v1'
  } catch {
    return false
  }
}

function loadPos(): { x: number; y: number } {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.pos)
    if (raw) {
      const p = JSON.parse(raw) as Record<string, unknown>
      if (typeof p.x === 'number' && typeof p.y === 'number') {
        return { x: p.x, y: p.y }
      }
    }
  } catch {
    // ignore
  }
  return { x: Math.max(8, window.innerWidth - 152), y: Math.max(8, window.innerHeight - 118) }
}

function loadDismissed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEYS.dismissed) === '1'
  } catch {
    return false
  }
}

export const useAgentStore = defineStore('agent', () => {
  const isOpen = ref(false)
  const mode = ref<ButlerMode>('idle')
  const consentGiven = ref(loadConsent())
  const showPermissionDialog = ref(false)
  const position = ref(loadPos())
  const dismissed = ref(loadDismissed())

  const messages = ref<AgentMessage[]>([])
  const pendingAction = ref<PendingAction | null>(null)
  const isLoading = ref(false)
  const currentConversationId = ref<number | null>(null)
  const orchestrationSession = ref<OrchestrationSession | null>(null)

  /** 未读消息（面板关闭时积累）*/
  const unreadCount = ref(0)
  /** 打开面板时滚动至文件收纳区（工作台顶栏溢出文件） */
  const focusFilesDrawer = ref(false)

  const isIdle = computed(() => mode.value === 'idle')

  function openPanel(opts?: { focusFiles?: boolean }) {
    if (!consentGiven.value) {
      showPermissionDialog.value = true
      return
    }
    if (opts?.focusFiles) focusFilesDrawer.value = true
    isOpen.value = true
    unreadCount.value = 0
  }

  function clearFilesDrawerFocus() {
    focusFilesDrawer.value = false
  }

  function closePanel() {
    isOpen.value = false
  }

  function grantConsent() {
    consentGiven.value = true
    showPermissionDialog.value = false
    try {
      localStorage.setItem(STORAGE_KEYS.consent, 'v1')
    } catch {
      // ignore
    }
    isOpen.value = true
  }

  function dismissLater() {
    showPermissionDialog.value = false
  }

  function dismissButler() {
    dismissed.value = true
    isOpen.value = false
    try {
      localStorage.setItem(STORAGE_KEYS.dismissed, '1')
    } catch {
      // ignore
    }
  }

  function restoreButler() {
    dismissed.value = false
    try {
      localStorage.removeItem(STORAGE_KEYS.dismissed)
    } catch {
      // ignore
    }
  }

  function setMode(m: ButlerMode) {
    mode.value = m
  }

  function savePosition(x: number, y: number) {
    position.value = { x, y }
    try {
      localStorage.setItem(STORAGE_KEYS.pos, JSON.stringify({ x, y }))
    } catch {
      // ignore
    }
  }

  function addMessage(msg: AgentMessage) {
    messages.value = [...messages.value, msg]
    if (!isOpen.value && msg.role !== 'system') {
      unreadCount.value += 1
    }
  }

  function updateLastMessage(patch: Partial<AgentMessage>) {
    const arr = messages.value
    if (!arr.length) return
    messages.value = [...arr.slice(0, -1), { ...arr[arr.length - 1], ...patch }]
  }

  function clearMessages() {
    messages.value = []
    currentConversationId.value = null
  }

  function setPendingAction(action: PendingAction | null) {
    pendingAction.value = action
    if (action) {
      mode.value = 'awaiting_confirm'
    } else if (mode.value === 'awaiting_confirm') {
      mode.value = 'idle'
    }
  }

  function clearOrchestration() {
    orchestrationSession.value = null
    if (mode.value === 'orchestrating') {
      mode.value = 'idle'
    }
  }

  return {
    isOpen,
    mode,
    consentGiven,
    showPermissionDialog,
    position,
    dismissed,
    messages,
    pendingAction,
    isLoading,
    currentConversationId,
    orchestrationSession,
    unreadCount,
    focusFilesDrawer,
    isIdle,
    openPanel,
    clearFilesDrawerFocus,
    closePanel,
    grantConsent,
    dismissLater,
    dismissButler,
    restoreButler,
    setMode,
    savePosition,
    addMessage,
    updateLastMessage,
    clearMessages,
    setPendingAction,
    clearOrchestration,
  }
})
