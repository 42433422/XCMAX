import type { TutorialBuildContext, TutorialStep, TutorialTrackId } from './types'
import { collectModStepsForTrack, injectModSteps } from './buildModSteps'
import { buildBasicSteps } from './tracks/basic'

export function resolveTrackSteps(trackId: TutorialTrackId, ctx: TutorialBuildContext): TutorialStep[] {
  const id = String(trackId || 'basic').trim() || 'basic'
  let steps: TutorialStep[]
  if (id === 'advanced') {
    // 进阶教程由 V2 服务端运行与验证器独占；旧 driver 菜单巡游不可再被
    // store、热身或历史调用入口恢复。
    steps = []
  } else if (id === 'basic') {
    steps = buildBasicSteps(ctx)
  } else {
    steps = injectModSteps([], collectModStepsForTrack(id, ctx.mods as never[]))
  }
  const modInjected = id === 'basic'
    ? injectModSteps(steps, collectModStepsForTrack(id, ctx.mods as never[]))
    : steps
  return modInjected
}

export function resolveAllWarmupSteps(ctx: TutorialBuildContext): TutorialStep[] {
  const basic = resolveTrackSteps('basic', ctx)
  const advanced = resolveTrackSteps('advanced', ctx)
  return dedupeById([...basic, ...advanced])
}

function dedupeById(steps: TutorialStep[]): TutorialStep[] {
  const seen = new Set<string>()
  const out: TutorialStep[] = []
  for (const s of steps) {
    if (seen.has(s.id)) continue
    seen.add(s.id)
    out.push(s)
  }
  return out
}
