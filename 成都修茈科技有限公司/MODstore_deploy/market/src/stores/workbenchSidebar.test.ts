import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  loadConversations: vi.fn(),
  saveConversations: vi.fn(),
  loadActiveId: vi.fn(),
  saveActiveId: vi.fn(),
}))

vi.mock('../utils/conversationStore', () => ({
  loadConversations: mocks.loadConversations,
  saveConversations: mocks.saveConversations,
  loadActiveId: mocks.loadActiveId,
  saveActiveId: mocks.saveActiveId,
}))

import { useWorkbenchSidebarStore } from './workbenchSidebar'
import type { Conversation } from '../utils/conversationStore'

function makeConv(id: string): Conversation {
  return {
    id,
    title: `title-${id}`,
    messages: [],
    createdAt: 1,
    updatedAt: 1,
  } as unknown as Conversation
}

describe('useWorkbenchSidebarStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mocks.loadConversations.mockReset()
    mocks.saveConversations.mockReset()
    mocks.loadActiveId.mockReset()
    mocks.saveActiveId.mockReset()
  })

  it('initializes with default state', () => {
    mocks.loadConversations.mockReturnValue([])
    mocks.loadActiveId.mockReturnValue('')
    const store = useWorkbenchSidebarStore()
    expect(store.conversations).toEqual([])
    expect(store.activeConversationId).toBe('')
    expect(store.activeMode).toBe('direct')
    expect(store.sidebarCollapsed).toBe(false)
    expect(store.mobileOpen).toBe(false)
    expect(store.activeConversation).toBe(null)
  })

  it('initConversations loads conversations and restores stored active id', () => {
    const convs = [makeConv('a'), makeConv('b')]
    mocks.loadConversations.mockReturnValue(convs)
    mocks.loadActiveId.mockReturnValue('b')
    const store = useWorkbenchSidebarStore()
    store.initConversations()
    expect(store.conversations).toEqual(convs)
    expect(store.activeConversationId).toBe('b')
  })

  it('initConversations falls back to first conversation when stored id is invalid', () => {
    const convs = [makeConv('a'), makeConv('b')]
    mocks.loadConversations.mockReturnValue(convs)
    mocks.loadActiveId.mockReturnValue('zzz')
    const store = useWorkbenchSidebarStore()
    store.initConversations()
    expect(store.activeConversationId).toBe('a')
    expect(mocks.saveActiveId).toHaveBeenCalledWith('a')
  })

  it('initConversations does not set active id when conversations is empty', () => {
    mocks.loadConversations.mockReturnValue([])
    mocks.loadActiveId.mockReturnValue('')
    const store = useWorkbenchSidebarStore()
    store.initConversations()
    expect(store.activeConversationId).toBe('')
    expect(mocks.saveActiveId).not.toHaveBeenCalled()
  })

  it('initConversations swallows errors from loadConversations', () => {
    mocks.loadConversations.mockImplementation(() => {
      throw new Error('boom')
    })
    const store = useWorkbenchSidebarStore()
    expect(() => store.initConversations()).not.toThrow()
  })

  it('pickConversation updates active id and persists', () => {
    const store = useWorkbenchSidebarStore()
    store.pickConversation('x')
    expect(store.activeConversationId).toBe('x')
    expect(mocks.saveActiveId).toHaveBeenCalledWith('x')
  })

  it('pickConversation is a no-op when id equals current active', () => {
    const store = useWorkbenchSidebarStore()
    store.setActiveConversationId('y')
    mocks.saveActiveId.mockClear()
    store.pickConversation('y')
    expect(mocks.saveActiveId).not.toHaveBeenCalled()
  })

  it('removeConversation removes the item and reassigns active', () => {
    const convs = [makeConv('a'), makeConv('b'), makeConv('c')]
    mocks.loadConversations.mockReturnValue(convs)
    const store = useWorkbenchSidebarStore()
    store.setConversations(convs)
    store.setActiveConversationId('b')
    mocks.saveActiveId.mockClear()
    mocks.saveConversations.mockClear()
    store.removeConversation('b')
    expect(store.conversations.map((c) => c.id)).toEqual(['a', 'c'])
    expect(store.activeConversationId).toBe('a')
    expect(mocks.saveActiveId).toHaveBeenCalledWith('a')
    expect(mocks.saveConversations).toHaveBeenCalled()
  })

  it('removeConversation clears active id when list becomes empty', () => {
    const convs = [makeConv('only')]
    const store = useWorkbenchSidebarStore()
    store.setConversations(convs)
    store.setActiveConversationId('only')
    mocks.saveActiveId.mockClear()
    store.removeConversation('only')
    expect(store.conversations).toEqual([])
    expect(store.activeConversationId).toBe('')
    expect(mocks.saveActiveId).toHaveBeenCalledWith('')
  })

  it('removeConversation does not change active when removing non-active', () => {
    const convs = [makeConv('a'), makeConv('b')]
    const store = useWorkbenchSidebarStore()
    store.setConversations(convs)
    store.setActiveConversationId('a')
    mocks.saveActiveId.mockClear()
    store.removeConversation('b')
    expect(store.activeConversationId).toBe('a')
    expect(mocks.saveActiveId).not.toHaveBeenCalled()
  })

  it('setActiveMode updates the active mode', () => {
    const store = useWorkbenchSidebarStore()
    expect(store.activeMode).toBe('direct')
    store.setActiveMode('make')
    expect(store.activeMode).toBe('make')
    store.setActiveMode('voice')
    expect(store.activeMode).toBe('voice')
  })

  it('closeMobile sets mobileOpen to false', () => {
    const store = useWorkbenchSidebarStore()
    store.$patch({ mobileOpen: true })
    store.closeMobile()
    expect(store.mobileOpen).toBe(false)
  })

  it('toggleMobileDrawer opens then closes', () => {
    const store = useWorkbenchSidebarStore()
    expect(store.mobileOpen).toBe(false)
    store.toggleMobileDrawer()
    expect(store.mobileOpen).toBe(true)
    expect(store.sidebarCollapsed).toBe(false)
    store.toggleMobileDrawer()
    expect(store.mobileOpen).toBe(false)
  })

  it('toggleMobileOpen delegates to toggleMobileDrawer (deprecated)', () => {
    const store = useWorkbenchSidebarStore()
    expect(store.mobileOpen).toBe(false)
    store.toggleMobileOpen()
    expect(store.mobileOpen).toBe(true)
  })

  it('updateConversation patches a conversation and persists', () => {
    const convs = [makeConv('a')]
    const store = useWorkbenchSidebarStore()
    store.setConversations(convs)
    mocks.saveConversations.mockClear()
    store.updateConversation('a', { title: 'updated' })
    expect(store.conversations[0].title).toBe('updated')
    expect(mocks.saveConversations).toHaveBeenCalled()
  })

  it('updateConversation is a no-op when id not found (map returns same)', () => {
    const convs = [makeConv('a')]
    const store = useWorkbenchSidebarStore()
    store.setConversations(convs)
    store.updateConversation('missing', { title: 'x' })
    expect(store.conversations[0].title).toBe('title-a')
  })

  it('setConversations replaces the list and persists', () => {
    const store = useWorkbenchSidebarStore()
    const convs = [makeConv('a'), makeConv('b')]
    store.setConversations(convs)
    expect(store.conversations).toEqual(convs)
    expect(mocks.saveConversations).toHaveBeenCalledWith(convs)
  })

  it('setActiveConversationId sets id and persists', () => {
    const store = useWorkbenchSidebarStore()
    store.setActiveConversationId('z')
    expect(store.activeConversationId).toBe('z')
    expect(mocks.saveActiveId).toHaveBeenCalledWith('z')
  })

  it('activeConversation getter returns matching conversation or null', () => {
    const convs = [makeConv('a'), makeConv('b')]
    const store = useWorkbenchSidebarStore()
    store.setConversations(convs)
    store.setActiveConversationId('b')
    expect(store.activeConversation?.id).toBe('b')
    store.setActiveConversationId('missing')
    expect(store.activeConversation).toBe(null)
  })

  it('persistConversations calls saveConversations with current list', () => {
    const store = useWorkbenchSidebarStore()
    const convs = [makeConv('a')]
    store.setConversations(convs)
    mocks.saveConversations.mockClear()
    store.persistConversations()
    expect(mocks.saveConversations).toHaveBeenCalledWith(convs)
  })
})
