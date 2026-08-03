import { useLoopRuntimeActivity } from './useLoopRuntimeActivity'
import { useLoopRuntimeCore } from './useLoopRuntimeCore'
import { useLoopRuntimePresentation } from './useLoopRuntimePresentation'
import type { LoopRuntimeConsoleDeps } from './loopRuntimeValues'

export { loopArray, loopFirstText, loopNumber, loopRecord, loopString } from './loopRuntimeValues'
export type { LoopRuntimeConsoleDeps } from './loopRuntimeValues'

export function useLoopRuntimeConsole(deps: LoopRuntimeConsoleDeps) {
  const core = useLoopRuntimeCore(deps)
  const activity = useLoopRuntimeActivity(core, deps)
  const presentation = useLoopRuntimePresentation(core, activity, deps)
  return { ...core, ...activity, ...presentation }
}

export type LoopRuntimeConsole = ReturnType<typeof useLoopRuntimeConsole>
