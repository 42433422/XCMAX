import { describe, expect, it, vi } from 'vitest'
import {
  publishButlerTask,
  subscribeButlerTask,
  buildButlerTaskPrompt,
} from './butlerTaskBus'

describe('butlerTaskBus', () => {
  it('publishButlerTask returns event with correct defaults', () => {
    const event = publishButlerTask({ source: 'test', employeeId: 'emp1', brief: 'do something' })
    expect(event.version).toBe(1)
    expect(event.source).toBe('test')
    expect(event.employeeId).toBe('emp1')
    expect(event.brief).toBe('do something')
    expect(event.includeDependencies).toBe(true)
    expect(event.allowHighRisk).toBe(false)
    expect(event.maxConcurrency).toBe(2)
    expect(event.inputData).toEqual({})
    expect(typeof event.eventId).toBe('string')
    expect(typeof event.emittedAt).toBe('number')
  })

  it('publishButlerTask defaults empty source to unknown', () => {
    const event = publishButlerTask({ source: '', employeeId: 'e', brief: 'b' } as any)
    expect(event.source).toBe('unknown')
  })

  it('publishButlerTask preserves optional fields', () => {
    const event = publishButlerTask({
      source: 'test',
      employeeId: 'emp1',
      brief: 'hi',
      employeeName: 'Bot',
      inputData: { key: 'val' },
      includeDependencies: false,
      allowHighRisk: true,
      maxConcurrency: 5,
    })
    expect(event.employeeName).toBe('Bot')
    expect(event.inputData).toEqual({ key: 'val' })
    expect(event.includeDependencies).toBe(false)
    expect(event.allowHighRisk).toBe(true)
    expect(event.maxConcurrency).toBe(5)
  })

  it('publishButlerTask handles non-object inputData', () => {
    const event = publishButlerTask({ source: 's', employeeId: 'e', brief: 'b', inputData: 'bad' } as any)
    expect(event.inputData).toEqual({})
  })

  it('publishButlerTask clamps maxConcurrency to 2 for invalid values', () => {
    const event = publishButlerTask({ source: 's', employeeId: 'e', brief: 'b', maxConcurrency: 0 } as any)
    expect(event.maxConcurrency).toBe(2)
  })

  it('publishButlerTask dispatches locally and subscriber receives event', () => {
    const handler = vi.fn()
    const unsub = subscribeButlerTask(handler)
    const event = publishButlerTask({ source: 'test', employeeId: 'emp1', brief: 'task' })
    expect(handler).toHaveBeenCalledWith(event)
    unsub()
  })

  it('subscribeButlerTask unsubscribes correctly', () => {
    const handler = vi.fn()
    const unsub = subscribeButlerTask(handler)
    unsub()
    publishButlerTask({ source: 'test', employeeId: 'emp1', brief: 'task' })
    expect(handler).not.toHaveBeenCalled()
  })

  it('buildButlerTaskPrompt with employeeName', () => {
    const event = publishButlerTask({ source: 's', employeeId: 'emp1', brief: 'task', employeeName: 'Bot' })
    const prompt = buildButlerTaskPrompt(event)
    expect(prompt).toContain('Bot (emp1)')
    expect(prompt).toContain('task')
  })

  it('buildButlerTaskPrompt without employeeName', () => {
    const event = publishButlerTask({ source: 's', employeeId: 'emp1', brief: 'task' })
    const prompt = buildButlerTaskPrompt(event)
    expect(prompt).toContain('目标员工：emp1')
  })

  it('buildButlerTaskPrompt includes risk and dependency info', () => {
    const event = publishButlerTask({ source: 's', employeeId: 'e', brief: 'b', allowHighRisk: true, includeDependencies: false })
    const prompt = buildButlerTaskPrompt(event)
    expect(prompt).toContain('include_dependencies=false')
    expect(prompt).toContain('allow_high_risk_real_run=true')
  })

  it('publishButlerTask generates unique eventIds', () => {
    const e1 = publishButlerTask({ source: 's', employeeId: 'e', brief: 'b' })
    const e2 = publishButlerTask({ source: 's', employeeId: 'e', brief: 'b' })
    expect(e1.eventId).not.toBe(e2.eventId)
  })

  it('trims invalid payloads, skips empty local dispatch, and prunes old seen ids', () => {
    const handler = vi.fn()
    const unsub = subscribeButlerTask(handler)

    const empty = publishButlerTask({ source: 's', employeeId: '  ', brief: '  ', maxConcurrency: Number.NaN } as any)
    expect(empty.employeeId).toBe('')
    expect(empty.brief).toBe('')
    expect(empty.maxConcurrency).toBe(2)
    expect(handler).not.toHaveBeenCalledWith(empty)

    for (let i = 0; i < 125; i++) {
      publishButlerTask({ source: 's', employeeId: `emp-${i}`, brief: `task-${i}` })
    }
    expect(handler).toHaveBeenCalled()
    unsub()
  })

  it('falls back to local delivery when BroadcastChannel is unavailable', async () => {
    vi.resetModules()
    vi.stubGlobal('BroadcastChannel', undefined)
    const mod = await import('./butlerTaskBus')
    const handler = vi.fn()
    const unsub = mod.subscribeButlerTask(handler)
    const event = mod.publishButlerTask({ source: 'dynamic', employeeId: 'emp', brief: 'brief' })

    expect(handler).toHaveBeenCalledWith(event)
    unsub()
    vi.unstubAllGlobals()
  })

  it('handles broadcast messages, ignores own events, and suppresses duplicates', async () => {
    vi.resetModules()
    const channels: FakeBroadcastChannel[] = []
    class FakeBroadcastChannel {
      listeners: Array<(event: MessageEvent) => void> = []
      postMessage = vi.fn()
      removeEventListener = vi.fn((type: string, cb: (event: MessageEvent) => void) => {
        if (type === 'message') this.listeners = this.listeners.filter((item) => item !== cb)
      })

      constructor(public name: string) {
        channels.push(this)
      }

      addEventListener(type: string, cb: (event: MessageEvent) => void) {
        if (type === 'message') this.listeners.push(cb)
      }

      emit(data: unknown) {
        for (const cb of this.listeners) cb({ data } as MessageEvent)
      }
    }
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel)
    const mod = await import('./butlerTaskBus')
    const received = vi.fn()
    const unsub = mod.subscribeButlerTask(received)
    const local = mod.publishButlerTask({ source: 'local', employeeId: 'emp', brief: 'brief' })
    const channel = channels[0]
    const posted = channel.postMessage.mock.calls[0][0]

    channel.emit(undefined)
    channel.emit({ topic: 'other' })
    channel.emit({ topic: posted.topic, originId: posted.originId, event: local })
    channel.emit({ topic: posted.topic, originId: 'remote', event: { eventId: 'bad' } })

    const remote = {
      ...local,
      eventId: 'remote-event',
      emittedAt: Date.now() + 1,
      source: 'remote',
      employeeId: 'remote-emp',
      brief: 'remote brief',
    }
    channel.emit({ topic: posted.topic, originId: 'remote-origin', event: remote })
    channel.emit({ topic: posted.topic, originId: 'remote-origin', event: remote })

    expect(received).toHaveBeenCalledWith(remote)
    expect(received.mock.calls.filter(([event]) => event.eventId === 'remote-event')).toHaveLength(1)
    unsub()
    expect(channel.removeEventListener).toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})
