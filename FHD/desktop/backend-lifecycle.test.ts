import { EventEmitter } from 'node:events'
import { describe, expect, it } from 'vitest'
import { terminateChildProcess, type StoppableChildProcess } from './backend-lifecycle'

class FakeChild extends EventEmitter implements StoppableChildProcess {
  exitCode: number | null = null
  signalCode: NodeJS.Signals | null = null
  readonly signals: Array<NodeJS.Signals | number | undefined> = []

  constructor(private readonly exitsOn: NodeJS.Signals | null) {
    super()
  }

  kill(signal?: NodeJS.Signals | number): boolean {
    this.signals.push(signal)
    if (signal === this.exitsOn) {
      queueMicrotask(() => {
        this.signalCode = signal as NodeJS.Signals
        this.emit('exit', null, signal)
      })
    }
    return true
  }
}

describe('terminateChildProcess', () => {
  it('waits for a graceful SIGTERM exit', async () => {
    const child = new FakeChild('SIGTERM')

    await expect(terminateChildProcess(child, 20, 20)).resolves.toBe('terminated')
    expect(child.signals).toEqual(['SIGTERM'])
  })

  it('falls back to SIGKILL when SIGTERM is ignored', async () => {
    const child = new FakeChild('SIGKILL')

    await expect(terminateChildProcess(child, 5, 20)).resolves.toBe('killed')
    expect(child.signals).toEqual(['SIGTERM', 'SIGKILL'])
  })

  it('does not signal a process that already exited', async () => {
    const child = new FakeChild(null)
    child.exitCode = 0

    await expect(terminateChildProcess(child, 5, 5)).resolves.toBe('already-exited')
    expect(child.signals).toEqual([])
  })
})
