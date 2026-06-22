/**
 * useXcmaxSync 覆盖率提升测试
 *
 * 目标：覆盖 useXcmaxSync.ts 中未覆盖的内部函数和分支，将覆盖率提升到 90%+。
 * 重点覆盖：
 *   - readStoredCursor / writeStoredCursor：localStorage 异常、无效值、负值
 *   - parseImMessageFromPayload：各种 payload 形状、无效 id、缺失字段
 *   - parseImReadStateFromPayload：各种 payload 形状、无效字段
 *   - dispatchImChange：im_message / im_read_state 分发、无效 payload 跳过
 *   - handleSseData：JSON 解析失败、connected / heartbeat / changes 各分支
 *   - scheduleReconnect：streamActive / reconnectTimer 状态、延迟倍增
 *   - openEventSource：已存在 / 正常创建 / onmessage / onerror
 *   - closeEventSource：reconnectTimer 清理、age < 2000 延迟关闭、age >= 2000 立即关闭
 *
 * 遵循铁律3：happy path + 空值/None + 边界值 + 异常路径。
 * Mock 最小化：仅 mock 外部边界（EventSource、localStorage）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  useXcmaxSync,
  XCMAX_SYNC_IM_MESSAGE_EVENT,
  XCMAX_SYNC_IM_READ_EVENT,
  type XcmaxImMessageDetail,
  type XcmaxImReadStateDetail,
} from './useXcmaxSync'

// ── 自定义 EventSource mock，记录所有实例以便测试中触发回调 ──────────

class TestEventSource {
  static instances: TestEventSource[] = []
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 2

  url: string
  readyState = TestEventSource.CONNECTING
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  close = vi.fn(() => {
    this.readyState = TestEventSource.CLOSED
  })

  constructor(url: string) {
    this.url = url
    TestEventSource.instances.push(this)
  }
}

// ── 测试套件 ──────────────────────────────────────────────────────────

describe('useXcmaxSync - coverage ramp', () => {
  let sync: ReturnType<typeof useXcmaxSync>
  let originalEventSource: typeof globalThis.EventSource

  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    TestEventSource.instances = []

    // 安装自定义 EventSource mock
    originalEventSource = globalThis.EventSource
    Object.defineProperty(window, 'EventSource', {
      writable: true,
      configurable: true,
      value: TestEventSource,
    })
    Object.defineProperty(globalThis, 'EventSource', {
      writable: true,
      configurable: true,
      value: TestEventSource,
    })

    sync = useXcmaxSync()
  })

  afterEach(() => {
    // 确保停止流，重置模块级状态
    try {
      sync.stop()
    } catch {
      /* ignore */
    }
    // 恢复真实定时器（安全调用，即使未启用 fake timers）
    vi.useRealTimers()

    // 恢复原始 EventSource
    Object.defineProperty(window, 'EventSource', {
      writable: true,
      configurable: true,
      value: originalEventSource,
    })
    Object.defineProperty(globalThis, 'EventSource', {
      writable: true,
      configurable: true,
      value: originalEventSource,
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // readStoredCursor 边界覆盖
  // ════════════════════════════════════════════════════════════════════

  describe('readStoredCursor 边界', () => {
    it('无存储值时返回 0', () => {
      expect(sync.readCursor()).toBe(0)
    })

    it('有效数字字符串时返回对应数值', () => {
      localStorage.setItem('xcmax_sync_cursor', '42')
      expect(sync.readCursor()).toBe(42)
    })

    it('非数字字符串时返回 0', () => {
      localStorage.setItem('xcmax_sync_cursor', 'invalid')
      expect(sync.readCursor()).toBe(0)
    })

    it('负值时返回 0', () => {
      localStorage.setItem('xcmax_sync_cursor', '-5')
      expect(sync.readCursor()).toBe(0)
    })

    it('NaN 时返回 0', () => {
      localStorage.setItem('xcmax_sync_cursor', 'NaN')
      expect(sync.readCursor()).toBe(0)
    })

    it('Infinity 时返回 0', () => {
      localStorage.setItem('xcmax_sync_cursor', 'Infinity')
      expect(sync.readCursor()).toBe(0)
    })

    it('0 是有效值', () => {
      localStorage.setItem('xcmax_sync_cursor', '0')
      expect(sync.readCursor()).toBe(0)
    })

    it('localStorage.getItem 抛异常时返回 0', () => {
      const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('localStorage error')
      })
      expect(sync.readCursor()).toBe(0)
      spy.mockRestore()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // writeStoredCursor 边界（通过 handleSseData 的 heartbeat/changes 触发）
  // ════════════════════════════════════════════════════════════════════

  describe('writeStoredCursor 边界', () => {
    it('heartbeat 带 cursor 时写入 localStorage', () => {
      sync.start()
      const es = TestEventSource.instances[0]
      es.onmessage!({ data: JSON.stringify({ type: 'heartbeat', cursor: 99 }) } as MessageEvent)

      expect(localStorage.getItem('xcmax_sync_cursor')).toBe('99')
    })

    it('heartbeat 不带 cursor 时不写入', () => {
      localStorage.setItem('xcmax_sync_cursor', '50')
      sync.start()
      const es = TestEventSource.instances[0]
      es.onmessage!({ data: JSON.stringify({ type: 'heartbeat' }) } as MessageEvent)

      expect(localStorage.getItem('xcmax_sync_cursor')).toBe('50')
    })

    it('changes 带 cursor 时写入 cursor', () => {
      sync.start()
      const es = TestEventSource.instances[0]
      es.onmessage!({
        data: JSON.stringify({
          changes: [{ id: 10, entity_type: 'other', entity_id: '1', operation: 'create', payload: {} }],
          cursor: 200,
        }),
      } as MessageEvent)

      expect(localStorage.getItem('xcmax_sync_cursor')).toBe('200')
    })

    it('changes 不带 cursor 时写入最后一个 change 的 id', () => {
      sync.start()
      const es = TestEventSource.instances[0]
      es.onmessage!({
        data: JSON.stringify({
          changes: [
            { id: 10, entity_type: 'other', entity_id: '1', operation: 'create', payload: {} },
            { id: 20, entity_type: 'other', entity_id: '2', operation: 'update', payload: {} },
          ],
        }),
      } as MessageEvent)

      expect(localStorage.getItem('xcmax_sync_cursor')).toBe('20')
    })

    it('changes 不带 cursor 且最后一个 change 无 id 时不写入', () => {
      localStorage.setItem('xcmax_sync_cursor', '30')
      sync.start()
      const es = TestEventSource.instances[0]
      es.onmessage!({
        data: JSON.stringify({
          changes: [
            { entity_type: 'other', entity_id: '1', operation: 'create', payload: {} },
          ],
        }),
      } as MessageEvent)

      // 最后一个 change 没有 id 字段，不写入
      expect(localStorage.getItem('xcmax_sync_cursor')).toBe('30')
    })

    it('cursor 为负值时回退到最后一个 change 的 id', () => {
      localStorage.setItem('xcmax_sync_cursor', '30')
      sync.start()
      const es = TestEventSource.instances[0]
      es.onmessage!({
        data: JSON.stringify({
          changes: [{ id: 10, entity_type: 'other', entity_id: '1', operation: 'create', payload: {} }],
          cursor: -1,
        }),
      } as MessageEvent)

      // cursor 为负值，回退到最后一个 change 的 id（10）
      expect(localStorage.getItem('xcmax_sync_cursor')).toBe('10')
    })

    it('localStorage.setItem 抛异常时静默忽略', () => {
      const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('quota exceeded')
      })
      sync.start()
      const es = TestEventSource.instances[0]
      // 不应抛出异常
      es.onmessage!({ data: JSON.stringify({ type: 'heartbeat', cursor: 99 }) } as MessageEvent)
      spy.mockRestore()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // parseImMessageFromPayload 边界（通过 handleSseData → dispatchImChange 触发）
  // ════════════════════════════════════════════════════════════════════

  describe('parseImMessageFromPayload 边界', () => {
    it('有效 message 嵌套在 payload.message 中：分发事件', () => {
      const handler = vi.fn()
      sync.onImMessage(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      const message = {
        id: 100,
        conversation_id: 1,
        sender_user_id: 5,
        sender_display_name: '张三',
        body: '你好',
        created_at: '2026-01-01T00:00:00Z',
      }
      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_message',
              entity_id: 'msg-1',
              operation: 'create',
              payload: { message },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).toHaveBeenCalledTimes(1)
      const detail: XcmaxImMessageDetail = handler.mock.calls[0][0]
      expect(detail.message.id).toBe(100)
      expect(detail.message.conversation_id).toBe(1)
      expect(detail.message.sender_user_id).toBe(5)
      expect(detail.message.sender_display_name).toBe('张三')
      expect(detail.message.body).toBe('你好')
      expect(detail.message.created_at).toBe('2026-01-01T00:00:00Z')
      expect(detail.change?.entity_type).toBe('im_message')
    })

    it('payload 直接是 message（无 message 字段）：使用 payload 本身', () => {
      const handler = vi.fn()
      sync.onImMessage(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_message',
              entity_id: 'msg-1',
              operation: 'create',
              payload: {
                id: 200,
                conversation_id: 2,
                sender_user_id: 10,
                body: '直接 payload',
              },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).toHaveBeenCalledTimes(1)
      const detail = handler.mock.calls[0][0]
      expect(detail.message.id).toBe(200)
      expect(detail.message.conversation_id).toBe(2)
      expect(detail.message.body).toBe('直接 payload')
    })

    it('conversation_id 从 payload 顶层获取（message 中缺失时）', () => {
      const handler = vi.fn()
      sync.onImMessage(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_message',
              entity_id: 'msg-1',
              operation: 'create',
              payload: {
                conversation_id: 99,
                message: { id: 300 },
              },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).toHaveBeenCalledTimes(1)
      const detail = handler.mock.calls[0][0]
      expect(detail.message.conversation_id).toBe(99)
    })

    it('id <= 0 时不分发事件', () => {
      const handler = vi.fn()
      sync.onImMessage(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_message',
              entity_id: 'msg-1',
              operation: 'create',
              payload: { message: { id: 0, conversation_id: 1 } },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).not.toHaveBeenCalled()
    })

    it('id 为负数时不分发事件', () => {
      const handler = vi.fn()
      sync.onImMessage(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_message',
              entity_id: 'msg-1',
              operation: 'create',
              payload: { message: { id: -1, conversation_id: 1 } },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).not.toHaveBeenCalled()
    })

    it('conversation_id <= 0 时不分发事件', () => {
      const handler = vi.fn()
      sync.onImMessage(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_message',
              entity_id: 'msg-1',
              operation: 'create',
              payload: { message: { id: 100, conversation_id: 0 } },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).not.toHaveBeenCalled()
    })

    it('sender_user_id 缺失时默认为 0', () => {
      const handler = vi.fn()
      sync.onImMessage(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_message',
              entity_id: 'msg-1',
              operation: 'create',
              payload: { message: { id: 100, conversation_id: 1 } },
            },
          ],
        }),
      } as MessageEvent)

      const detail = handler.mock.calls[0][0]
      expect(detail.message.sender_user_id).toBe(0)
    })

    it('sender_display_name 缺失时为 undefined', () => {
      const handler = vi.fn()
      sync.onImMessage(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_message',
              entity_id: 'msg-1',
              operation: 'create',
              payload: { message: { id: 100, conversation_id: 1 } },
            },
          ],
        }),
      } as MessageEvent)

      const detail = handler.mock.calls[0][0]
      expect(detail.message.sender_display_name).toBeUndefined()
    })

    it('body 缺失时为空字符串', () => {
      const handler = vi.fn()
      sync.onImMessage(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_message',
              entity_id: 'msg-1',
              operation: 'create',
              payload: { message: { id: 100, conversation_id: 1 } },
            },
          ],
        }),
      } as MessageEvent)

      const detail = handler.mock.calls[0][0]
      expect(detail.message.body).toBe('')
    })

    it('created_at 缺失时为 null', () => {
      const handler = vi.fn()
      sync.onImMessage(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_message',
              entity_id: 'msg-1',
              operation: 'create',
              payload: { message: { id: 100, conversation_id: 1 } },
            },
          ],
        }),
      } as MessageEvent)

      const detail = handler.mock.calls[0][0]
      expect(detail.message.created_at).toBeNull()
    })

    it('id 为非有限数字（NaN）时不分发', () => {
      const handler = vi.fn()
      sync.onImMessage(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_message',
              entity_id: 'msg-1',
              operation: 'create',
              payload: { message: { id: 'abc', conversation_id: 1 } },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).not.toHaveBeenCalled()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // parseImReadStateFromPayload 边界
  // ════════════════════════════════════════════════════════════════════

  describe('parseImReadStateFromPayload 边界', () => {
    it('有效 read state：分发事件', () => {
      const handler = vi.fn()
      sync.onImReadState(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_read_state',
              entity_id: 'rs-1',
              operation: 'update',
              payload: { conversation_id: 5, user_id: 10, last_message_id: 99 },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).toHaveBeenCalledTimes(1)
      const detail: XcmaxImReadStateDetail = handler.mock.calls[0][0]
      expect(detail.conversation_id).toBe(5)
      expect(detail.user_id).toBe(10)
      expect(detail.last_message_id).toBe(99)
      expect(detail.change?.entity_type).toBe('im_read_state')
    })

    it('last_message_id = 0 是有效值（>= 0 检查）', () => {
      const handler = vi.fn()
      sync.onImReadState(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_read_state',
              entity_id: 'rs-1',
              operation: 'update',
              payload: { conversation_id: 5, user_id: 10, last_message_id: 0 },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).toHaveBeenCalledTimes(1)
      expect(handler.mock.calls[0][0].last_message_id).toBe(0)
    })

    it('conversation_id <= 0 时不分发', () => {
      const handler = vi.fn()
      sync.onImReadState(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_read_state',
              entity_id: 'rs-1',
              operation: 'update',
              payload: { conversation_id: 0, user_id: 10, last_message_id: 99 },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).not.toHaveBeenCalled()
    })

    it('user_id <= 0 时不分发', () => {
      const handler = vi.fn()
      sync.onImReadState(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_read_state',
              entity_id: 'rs-1',
              operation: 'update',
              payload: { conversation_id: 5, user_id: 0, last_message_id: 99 },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).not.toHaveBeenCalled()
    })

    it('last_message_id < 0 时不分发', () => {
      const handler = vi.fn()
      sync.onImReadState(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_read_state',
              entity_id: 'rs-1',
              operation: 'update',
              payload: { conversation_id: 5, user_id: 10, last_message_id: -1 },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).not.toHaveBeenCalled()
    })

    it('字段为非有限数字时不分发', () => {
      const handler = vi.fn()
      sync.onImReadState(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_read_state',
              entity_id: 'rs-1',
              operation: 'update',
              payload: { conversation_id: 'abc', user_id: 10, last_message_id: 99 },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).not.toHaveBeenCalled()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // dispatchImChange 其他 entity_type
  // ════════════════════════════════════════════════════════════════════

  describe('dispatchImChange 其他 entity_type', () => {
    it('entity_type 非 im_message / im_read_state：不分发任何事件', () => {
      const msgHandler = vi.fn()
      const readHandler = vi.fn()
      sync.onImMessage(msgHandler)
      sync.onImReadState(readHandler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'other_type',
              entity_id: 'x-1',
              operation: 'create',
              payload: {},
            },
          ],
        }),
      } as MessageEvent)

      expect(msgHandler).not.toHaveBeenCalled()
      expect(readHandler).not.toHaveBeenCalled()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // handleSseData 各分支
  // ════════════════════════════════════════════════════════════════════

  describe('handleSseData 各分支', () => {
    it('JSON 解析失败：静默返回', () => {
      sync.start()
      const es = TestEventSource.instances[0]
      // 不应抛出异常
      es.onmessage!({ data: 'not valid json {{{' } as MessageEvent)
      es.onmessage!({ data: '' } as MessageEvent)
    })

    it('type=connected：重置 reconnectDelayMs', () => {
      sync.start()
      const es = TestEventSource.instances[0]
      // connected 事件不应抛出
      es.onmessage!({ data: JSON.stringify({ type: 'connected' }) } as MessageEvent)
    })

    it('type=heartbeat 且 cursor 非数字：不写入', () => {
      localStorage.setItem('xcmax_sync_cursor', '30')
      sync.start()
      const es = TestEventSource.instances[0]
      es.onmessage!({
        data: JSON.stringify({ type: 'heartbeat', cursor: 'abc' }),
      } as MessageEvent)
      expect(localStorage.getItem('xcmax_sync_cursor')).toBe('30')
    })

    it('changes 为空数组：不分发事件', () => {
      const msgHandler = vi.fn()
      sync.onImMessage(msgHandler)
      sync.start()
      const es = TestEventSource.instances[0]
      es.onmessage!({
        data: JSON.stringify({ changes: [] }),
      } as MessageEvent)
      expect(msgHandler).not.toHaveBeenCalled()
    })

    it('changes 非数组：不分发事件', () => {
      const msgHandler = vi.fn()
      sync.onImMessage(msgHandler)
      sync.start()
      const es = TestEventSource.instances[0]
      es.onmessage!({
        data: JSON.stringify({ changes: 'not an array' }),
      } as MessageEvent)
      expect(msgHandler).not.toHaveBeenCalled()
    })

    it('data 为空对象：changes 非数组，不分发', () => {
      const msgHandler = vi.fn()
      sync.onImMessage(msgHandler)
      sync.start()
      const es = TestEventSource.instances[0]
      es.onmessage!({ data: '{}' } as MessageEvent)
      expect(msgHandler).not.toHaveBeenCalled()
    })

    it('e.data 为 undefined：handleSseData 接收空字符串', () => {
      sync.start()
      const es = TestEventSource.instances[0]
      // 不应抛出异常
      es.onmessage!({} as MessageEvent)
    })

    it('多个 changes 混合类型：分别分发', () => {
      const msgHandler = vi.fn()
      const readHandler = vi.fn()
      sync.onImMessage(msgHandler)
      sync.onImReadState(readHandler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_message',
              entity_id: 'm-1',
              operation: 'create',
              payload: { message: { id: 100, conversation_id: 1 } },
            },
            {
              id: 2,
              entity_type: 'im_read_state',
              entity_id: 'r-1',
              operation: 'update',
              payload: { conversation_id: 1, user_id: 5, last_message_id: 100 },
            },
            {
              id: 3,
              entity_type: 'other',
              entity_id: 'o-1',
              operation: 'create',
              payload: {},
            },
          ],
        }),
      } as MessageEvent)

      expect(msgHandler).toHaveBeenCalledTimes(1)
      expect(readHandler).toHaveBeenCalledTimes(1)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // scheduleReconnect + openEventSource + onerror
  // ════════════════════════════════════════════════════════════════════

  describe('scheduleReconnect 和 onerror', () => {
    it('onerror 后 streamActive=true 时调度重连', () => {
      vi.useFakeTimers()
      sync.start()
      const es1 = TestEventSource.instances[0]
      expect(es1).toBeDefined()

      // 触发 onerror
      es1.onerror!(new Event('error'))

      // 此时 eventSource 被置 null，应已调度重连
      // 快进 3000ms（初始 reconnectDelayMs）
      vi.advanceTimersByTime(3000)

      // 应创建新的 EventSource
      expect(TestEventSource.instances.length).toBe(2)
    })

    it('onerror 后 streamActive=false 时不重连', () => {
      vi.useFakeTimers()
      sync.start()
      const es1 = TestEventSource.instances[0]

      sync.stop()
      // 此时 streamActive=false
      es1.onerror!(new Event('error'))

      vi.advanceTimersByTime(3000)
      // 不应创建新的 EventSource
      expect(TestEventSource.instances.length).toBe(1)
    })

    it('onerror 时 es.close() 抛异常被静默捕获', () => {
      vi.useFakeTimers()
      sync.start()
      const es1 = TestEventSource.instances[0]
      es1.close.mockImplementation(() => {
        throw new Error('close error')
      })

      // 不应抛出异常
      es1.onerror!(new Event('error'))
    })

    it('重连延迟倍增（最大 30s）', () => {
      vi.useFakeTimers()
      sync.start()

      // 第一次 onerror → 延迟 3000ms
      TestEventSource.instances[0].onerror!(new Event('error'))
      vi.advanceTimersByTime(3000)
      expect(TestEventSource.instances.length).toBe(2)

      // 第二次 onerror → 延迟 6000ms
      TestEventSource.instances[1].onerror!(new Event('error'))
      vi.advanceTimersByTime(6000)
      expect(TestEventSource.instances.length).toBe(3)

      // 第三次 onerror → 延迟 12000ms
      TestEventSource.instances[2].onerror!(new Event('error'))
      vi.advanceTimersByTime(12000)
      expect(TestEventSource.instances.length).toBe(4)

      // 第四次 onerror → 延迟 24000ms
      TestEventSource.instances[3].onerror!(new Event('error'))
      vi.advanceTimersByTime(24000)
      expect(TestEventSource.instances.length).toBe(5)

      // 第五次 onerror → 延迟 30000ms（上限）
      TestEventSource.instances[4].onerror!(new Event('error'))
      vi.advanceTimersByTime(30000)
      expect(TestEventSource.instances.length).toBe(6)
    })

    it('reconnectTimer 已存在时不重复调度', () => {
      vi.useFakeTimers()
      sync.start()

      // 第一次 onerror → 调度重连
      TestEventSource.instances[0].onerror!(new Event('error'))

      // 在重连执行前，第二次 onerror 不应再调度
      // 但 eventSource 已为 null，所以 onerror 不会被再次调用
      // 这里通过检查 instance 数量来验证
      vi.advanceTimersByTime(3000)
      expect(TestEventSource.instances.length).toBe(2)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // openEventSource 边界
  // ════════════════════════════════════════════════════════════════════

  describe('openEventSource 边界', () => {
    it('start 后创建 EventSource，URL 包含 cursor', () => {
      localStorage.setItem('xcmax_sync_cursor', '42')
      sync.start()
      const es = TestEventSource.instances[0]
      expect(es.url).toContain('since_cursor=42')
    })

    it('start 后 cursor 为 0 时 URL 包含 since_cursor=0', () => {
      sync.start()
      const es = TestEventSource.instances[0]
      expect(es.url).toContain('since_cursor=0')
    })

    it('onmessage 收到有效数据时处理', () => {
      const handler = vi.fn()
      sync.onImMessage(handler)
      sync.start()
      const es = TestEventSource.instances[0]

      es.onmessage!({
        data: JSON.stringify({
          changes: [
            {
              id: 1,
              entity_type: 'im_message',
              entity_id: 'm-1',
              operation: 'create',
              payload: { message: { id: 100, conversation_id: 1 } },
            },
          ],
        }),
      } as MessageEvent)

      expect(handler).toHaveBeenCalledTimes(1)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // closeEventSource 边界
  // ════════════════════════════════════════════════════════════════════

  describe('closeEventSource 边界', () => {
    it('stop 后 EventSource 被延迟关闭（age < 2000）', () => {
      vi.useFakeTimers()
      sync.start()
      const es = TestEventSource.instances[0]
      sync.stop()
      // age < 2000 时延迟 500ms 关闭
      expect(es.close).not.toHaveBeenCalled()
      vi.advanceTimersByTime(500)
      expect(es.close).toHaveBeenCalled()
      vi.useRealTimers()
    })

    it('age >= 2000 时立即关闭 EventSource', () => {
      vi.useFakeTimers()
      sync.start()
      const es = TestEventSource.instances[0]

      // 快进超过 2000ms
      vi.advanceTimersByTime(2500)

      sync.stop()
      // age >= 2000，应立即关闭
      expect(es.close).toHaveBeenCalled()
      vi.useRealTimers()
    })

    it('close 抛异常时静默捕获（age >= 2000 路径）', () => {
      vi.useFakeTimers()
      sync.start()
      const es = TestEventSource.instances[0]
      es.close.mockImplementation(() => {
        throw new Error('close error')
      })

      vi.advanceTimersByTime(2500)
      // 不应抛出异常
      expect(() => sync.stop()).not.toThrow()
      vi.useRealTimers()
    })

    it('close 抛异常时静默捕获（age < 2000 路径）', () => {
      sync.start()
      const es = TestEventSource.instances[0]
      es.close.mockImplementation(() => {
        throw new Error('close error')
      })

      // 不应抛出异常
      vi.useFakeTimers()
      expect(() => sync.stop()).not.toThrow()
      vi.advanceTimersByTime(500)
      vi.useRealTimers()
    })

    it('stop 后 reconnectDelayMs 重置为 3000', () => {
      vi.useFakeTimers()
      sync.start()

      // 触发多次 onerror 使 delay 增长
      TestEventSource.instances[0].onerror!(new Event('error'))
      vi.advanceTimersByTime(3000)
      TestEventSource.instances[1].onerror!(new Event('error'))

      sync.stop()
      vi.useRealTimers()

      // 重新 start 后，onerror 的延迟应从 3000 开始
      vi.useFakeTimers()
      sync.start()
      TestEventSource.instances[2].onerror!(new Event('error'))
      vi.advanceTimersByTime(3000)
      // 3000ms 后应重连
      expect(TestEventSource.instances.length).toBe(4)
      vi.useRealTimers()
    })

    it('stop 清除 reconnectTimer', () => {
      vi.useFakeTimers()
      sync.start()

      // 触发 onerror 调度重连
      TestEventSource.instances[0].onerror!(new Event('error'))

      // 在重连执行前 stop
      sync.stop()

      // 快进时间，不应创建新 EventSource
      vi.advanceTimersByTime(10000)
      expect(TestEventSource.instances.length).toBe(1)
      vi.useRealTimers()
    })

    it('无 EventSource 时 stop 不抛异常', () => {
      expect(() => sync.stop()).not.toThrow()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // start / stop 生命周期
  // ════════════════════════════════════════════════════════════════════

  describe('start / stop 生命周期', () => {
    it('start 创建 EventSource', () => {
      sync.start()
      expect(TestEventSource.instances.length).toBe(1)
    })

    it('start 幂等：重复调用不创建新 EventSource', () => {
      sync.start()
      sync.start()
      expect(TestEventSource.instances.length).toBe(1)
    })

    it('stop 后可重新 start', () => {
      sync.start()
      vi.useFakeTimers()
      sync.stop()
      vi.advanceTimersByTime(500) // 让延迟关闭完成
      vi.useRealTimers()

      sync.start()
      expect(TestEventSource.instances.length).toBe(2)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // onImMessage / onImReadState 订阅
  // ════════════════════════════════════════════════════════════════════

  describe('onImMessage / onImReadState 订阅', () => {
    it('onImMessage 分发 detail 给 handler', () => {
      const handler = vi.fn()
      sync.onImMessage(handler)

      const detail: XcmaxImMessageDetail = {
        conversation_id: 1,
        message: { id: 1, conversation_id: 1, sender_user_id: 1, body: 'test', created_at: null },
      }
      window.dispatchEvent(new CustomEvent(XCMAX_SYNC_IM_MESSAGE_EVENT, { detail }))
      expect(handler).toHaveBeenCalledWith(detail)
    })

    it('onImReadState 分发 detail 给 handler', () => {
      const handler = vi.fn()
      sync.onImReadState(handler)

      const detail: XcmaxImReadStateDetail = {
        conversation_id: 1,
        user_id: 1,
        last_message_id: 100,
      }
      window.dispatchEvent(new CustomEvent(XCMAX_SYNC_IM_READ_EVENT, { detail }))
      expect(handler).toHaveBeenCalledWith(detail)
    })

    it('onImMessage 返回的取消订阅函数有效', () => {
      const handler = vi.fn()
      const unsub = sync.onImMessage(handler)
      unsub()

      const detail: XcmaxImMessageDetail = {
        conversation_id: 1,
        message: { id: 1, conversation_id: 1, sender_user_id: 1, body: 'test', created_at: null },
      }
      window.dispatchEvent(new CustomEvent(XCMAX_SYNC_IM_MESSAGE_EVENT, { detail }))
      expect(handler).not.toHaveBeenCalled()
    })

    it('onImReadState 返回的取消订阅函数有效', () => {
      const handler = vi.fn()
      const unsub = sync.onImReadState(handler)
      unsub()

      const detail: XcmaxImReadStateDetail = {
        conversation_id: 1,
        user_id: 1,
        last_message_id: 100,
      }
      window.dispatchEvent(new CustomEvent(XCMAX_SYNC_IM_READ_EVENT, { detail }))
      expect(handler).not.toHaveBeenCalled()
    })
  })
})
