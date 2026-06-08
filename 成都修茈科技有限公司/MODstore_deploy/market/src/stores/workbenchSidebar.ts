import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Conversation } from '../utils/conversationStore'
import {
  loadConversations,
  saveConversations,
  loadActiveId,
  saveActiveId,
} from '../utils/conversationStore'

export const useWorkbenchSidebarStore = defineStore('workbenchSidebar', () => {
  const conversations = ref<Conversation[]>([])
  const activeConversationId = ref('')
  const activeMode = ref<'direct' | 'make' | 'voice'>('direct')
  const sidebarCollapsed = ref(false)
  const mobileOpen = ref(false)

  const activeConversation = computed(() =>
    conversations.value.find((c) => c.id === activeConversationId.value) ?? null,
  )

  function initConversations() {
    try {
      conversations.value = loadConversations()
      const storedActive = loadActiveId()
      if (storedActive && conversations.value.some((c) => c.id === storedActive)) {
        activeConversationId.value = storedActive
      } else if (conversations.value.length) {
        activeConversationId.value = conversations.value[0].id
        saveActiveId(activeConversationId.value)
      }
    } catch {
      /* ignore */
    }
  }

  function persistConversations() {
    saveConversations(conversations.value)
  }

  function pickConversation(id: string) {
    if (id === activeConversationId.value) return
    activeConversationId.value = id
    saveActiveId(id)
  }

  function removeConversation(id: string) {
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (activeConversationId.value === id) {
      activeConversationId.value = conversations.value[0]?.id || ''
      saveActiveId(activeConversationId.value)
    }
    persistConversations()
  }

  function setActiveMode(mode: 'direct' | 'make' | 'voice') {
    activeMode.value = mode
  }

  function isMobileViewport(): boolean {
    return typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches
  }

  /** Mobile drawer: only toggles mobileOpen; never applies desktop collapsed rail. */
  function toggleMobileDrawer() {
    if (mobileOpen.value) {
      closeMobile()
      return
    }
    sidebarCollapsed.value = false
    mobileOpen.value = true
  }

  function toggleSidebar() {
    if (isMobileViewport()) {
      toggleMobileDrawer()
      return
    }
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  /** @deprecated Prefer toggleMobileDrawer — kept for call sites. */
  function toggleMobileOpen() {
    toggleMobileDrawer()
  }

  function closeMobile() {
    mobileOpen.value = false
  }

  function updateConversation(id: string, patch: Partial<Conversation>) {
    conversations.value = conversations.value.map((c) =>
      c.id === id ? { ...c, ...patch, updatedAt: Date.now() } : c,
    )
    persistConversations()
  }

  function setConversations(list: Conversation[]) {
    conversations.value = list
    persistConversations()
  }

  function setActiveConversationId(id: string) {
    activeConversationId.value = id
    saveActiveId(id)
  }

  return {
    conversations,
    activeConversationId,
    activeConversation,
    activeMode,
    sidebarCollapsed,
    mobileOpen,
    initConversations,
    persistConversations,
    pickConversation,
    removeConversation,
    setActiveMode,
    toggleSidebar,
    toggleMobileDrawer,
    toggleMobileOpen,
    closeMobile,
    updateConversation,
    setConversations,
    setActiveConversationId,
  }
})
