import { EventEmitter } from 'node:events'
import { describe, expect, it, vi } from 'vitest'
import { relayBackendOutput, terminateChildProcess, type StoppableChildProcess } from './backend-lifecycle'

it.each(['stdout', 'stderr'] as const)('packaged %s survives a closed parent pipe', channel => {
  const pipe = vi.spyOn(process[channel], 'write').mockImplementation(() => { throw new Error('EPIPE') })
  const log = vi.fn()
  try {
    relayBackendOutput(channel, Buffer.from('backup receipt\n'), true, log, 'migrate')
    expect(log).toHaveBeenCalledWith(`[${channel}] backup receipt\n`)
    expect(pipe).not.toHaveBeenCalled()
  } finally {
    pipe.mockRestore()
  }
})

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
