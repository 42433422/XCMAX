export interface StoppableChildProcess {
  exitCode: number | null
  signalCode: NodeJS.Signals | null
  kill(signal?: NodeJS.Signals | number): boolean
  once(event: 'exit', listener: (code: number | null, signal: NodeJS.Signals | null) => void): this
  removeListener(event: 'exit', listener: (code: number | null, signal: NodeJS.Signals | null) => void): this
}

export type ChildStopResult = 'already-exited' | 'terminated' | 'killed' | 'kill-timeout'

function hasExited(child: StoppableChildProcess): boolean {
  return child.exitCode !== null || child.signalCode !== null
}

export function waitForChildExit(child: StoppableChildProcess, timeoutMs: number): Promise<boolean> {
  if (hasExited(child)) {
    return Promise.resolve(true)
  }

  return new Promise(resolve => {
    let settled = false
    let timer: NodeJS.Timeout
    const finish = (exited: boolean) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      child.removeListener('exit', onExit)
      resolve(exited)
    }
    const onExit = () => finish(true)

    child.once('exit', onExit)
    timer = setTimeout(() => finish(hasExited(child)), Math.max(0, timeoutMs))
  })
}

/**
 * Give the packaged backend a short graceful-shutdown window, then force it down.
 * Merely sending SIGTERM is not enough: Electron can exit first and leave an orphan.
 */
export async function terminateChildProcess(
  child: StoppableChildProcess,
  gracefulTimeoutMs = 2000,
  forceTimeoutMs = 500,
): Promise<ChildStopResult> {
  if (hasExited(child)) {
    return 'already-exited'
  }

  const gracefulExit = waitForChildExit(child, gracefulTimeoutMs)
  try {
    child.kill('SIGTERM')
  } catch {
    // Continue to the forced path below.
  }
  if (await gracefulExit) {
    return 'terminated'
  }

  const forcedExit = waitForChildExit(child, forceTimeoutMs)
  try {
    child.kill('SIGKILL')
  } catch {
    // The process may have exited between the timeout and this signal.
  }
  return (await forcedExit) ? 'killed' : 'kill-timeout'
}
