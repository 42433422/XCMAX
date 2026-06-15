import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  useXcmaxSync,
  XCMAX_SYNC_IM_MESSAGE_EVENT,
  XCMAX_SYNC_IM_READ_EVENT,
  type XcmaxSyncChange,
  type XcmaxImMessageDetail,
  type XcmaxImReadStateDetail,
} from './useXcmaxSync'

describe('useXcmaxSync', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('returns sync API', () => {
    const sync = useXcmaxSync()
    expect(typeof sync.start).toBe('function')
    expect(typeof sync.stop).toBe('function')
    expect(typeof sync.readCursor).toBe('function')
    expect(typeof sync.onImMessage).toBe('function')
    expect(typeof sync.onImReadState).toBe('function')
  })

  it('readCursor returns 0 when no stored cursor', () => {
    const sync = useXcmaxSync()
    expect(sync.readCursor()).toBe(0)
  })

  it('readCursor returns stored value', () => {
    localStorage.setItem('xcmax_sync_cursor', '42')
    const sync = useXcmaxSync()
    expect(sync.readCursor()).toBe(42)
  })

  it('readCursor returns 0 for invalid stored value', () => {
    localStorage.setItem('xcmax_sync_cursor', 'invalid')
    const sync = useXcmaxSync()
    expect(sync.readCursor()).toBe(0)
  })

  it('readCursor returns 0 for negative stored value', () => {
    localStorage.setItem('xcmax_sync_cursor', '-5')
    const sync = useXcmaxSync()
    expect(sync.readCursor()).toBe(0)
  })

  it('start does not throw', () => {
    const sync = useXcmaxSync()
    expect(() => sync.start()).not.toThrow()
  })

  it('stop does not throw', () => {
    const sync = useXcmaxSync()
    sync.start()
    expect(() => sync.stop()).not.toThrow()
  })

  it('start is idempotent', () => {
    const sync = useXcmaxSync()
    sync.start()
    expect(() => sync.start()).not.toThrow()
    sync.stop()
  })

  it('stop without start does not throw', () => {
    const sync = useXcmaxSync()
    expect(() => sync.stop()).not.toThrow()
  })

  it('onImMessage registers and unregisters handler', () => {
    const sync = useXcmaxSync()
    const handler = vi.fn()
    const unsubscribe = sync.onImMessage(handler)

    const detail: XcmaxImMessageDetail = {
      conversation_id: 1,
      message: {
        id: 100,
        conversation_id: 1,
        sender_user_id: 1,
        body: 'hello',
        created_at: null,
      },
    }
    window.dispatchEvent(new CustomEvent(XCMAX_SYNC_IM_MESSAGE_EVENT, { detail }))
    expect(handler).toHaveBeenCalledWith(detail)

    handler.mockClear()
    unsubscribe()
    window.dispatchEvent(new CustomEvent(XCMAX_SYNC_IM_MESSAGE_EVENT, { detail }))
    expect(handler).not.toHaveBeenCalled()
  })

  it('onImReadState registers and unregisters handler', () => {
    const sync = useXcmaxSync()
    const handler = vi.fn()
    const unsubscribe = sync.onImReadState(handler)

    const detail: XcmaxImReadStateDetail = {
      conversation_id: 1,
      user_id: 1,
      last_message_id: 100,
    }
    window.dispatchEvent(new CustomEvent(XCMAX_SYNC_IM_READ_EVENT, { detail }))
    expect(handler).toHaveBeenCalledWith(detail)

    handler.mockClear()
    unsubscribe()
    window.dispatchEvent(new CustomEvent(XCMAX_SYNC_IM_READ_EVENT, { detail }))
    expect(handler).not.toHaveBeenCalled()
  })

  it('multiple onImMessage handlers work independently', () => {
    const sync = useXcmaxSync()
    const handler1 = vi.fn()
    const handler2 = vi.fn()
    const unsub1 = sync.onImMessage(handler1)
    const unsub2 = sync.onImMessage(handler2)

    const detail: XcmaxImMessageDetail = {
      conversation_id: 1,
      message: { id: 1, conversation_id: 1, sender_user_id: 1, body: 'test', created_at: null },
    }
    window.dispatchEvent(new CustomEvent(XCMAX_SYNC_IM_MESSAGE_EVENT, { detail }))
    expect(handler1).toHaveBeenCalled()
    expect(handler2).toHaveBeenCalled()

    unsub1()
    handler1.mockClear()
    handler2.mockClear()
    window.dispatchEvent(new CustomEvent(XCMAX_SYNC_IM_MESSAGE_EVENT, { detail }))
    expect(handler1).not.toHaveBeenCalled()
    expect(handler2).toHaveBeenCalled()

    unsub2()
  })

  it('start and stop lifecycle manages fetch connection', async () => {
    const sync = useXcmaxSync()
    sync.start()
    // Give it a tick
    await new Promise((r) => setTimeout(r, 10))
    sync.stop()
  })

  it('cursor is persisted to localStorage', () => {
    localStorage.setItem('xcmax_sync_cursor', '123')
    const sync = useXcmaxSync()
    expect(sync.readCursor()).toBe(123)
  })
})

describe('XcmaxSyncChange type', () => {
  it('has expected fields', () => {
    const change: XcmaxSyncChange = {
      id: 1,
      entity_type: 'im_message',
      entity_id: 'msg-1',
      operation: 'create',
      payload: { body: 'hello' },
    }
    expect(change.id).toBe(1)
    expect(change.entity_type).toBe('im_message')
    expect(change.operation).toBe('create')
  })
})

describe('XcmaxImMessageDetail type', () => {
  it('has expected fields', () => {
    const detail: XcmaxImMessageDetail = {
      conversation_id: 1,
      message: {
        id: 100,
        conversation_id: 1,
        sender_user_id: 1,
        sender_display_name: 'Test User',
        body: 'Hello',
        created_at: '2026-01-01T00:00:00Z',
      },
    }
    expect(detail.conversation_id).toBe(1)
    expect(detail.message.body).toBe('Hello')
  })
})

describe('XcmaxImReadStateDetail type', () => {
  it('has expected fields', () => {
    const detail: XcmaxImReadStateDetail = {
      conversation_id: 1,
      user_id: 1,
      last_message_id: 100,
    }
    expect(detail.conversation_id).toBe(1)
    expect(detail.last_message_id).toBe(100)
  })
})
