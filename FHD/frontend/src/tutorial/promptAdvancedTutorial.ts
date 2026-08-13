import type { Router } from 'vue-router'
import { appConfirm } from '@/utils/appDialog'
import type { OnboardingReturnContext } from '@/stores/onboardingTutorial'
import type { TutorialBuildContext } from '@/tutorial/types'

const DEFAULT_INSTALL_MESSAGE =
  '安装已完成，可以开始使用了。\n\n是否现在打开进阶教程，进入真实业务实训课程？'

export async function launchAdvancedDriverTour(options: {
  router: Router
  buildContext: TutorialBuildContext
  returnContext?: OnboardingReturnContext
  skipNavigation?: boolean
}): Promise<boolean> {
  void options
  if (typeof window === 'undefined') return false
  window.dispatchEvent(new CustomEvent('xcagi:open-assistant-float', {
    detail: { feature: 'tutorial', advanced: true },
  }))
  return true
}

export type InstallTutorialPromptResult = 'started' | 'dismissed' | 'already_completed'

export async function promptAdvancedTutorialAfterInstall(options: {
  router: Router
  buildContext: TutorialBuildContext
  message?: string
  returnContext?: OnboardingReturnContext
  skipIfCompleted?: boolean
}): Promise<InstallTutorialPromptResult> {
  const {
    router,
    buildContext,
    message = DEFAULT_INSTALL_MESSAGE,
    returnContext,
    skipIfCompleted = true,
  } = options

  // V1 local completion is deliberately ignored: it is not V2 course evidence.
  void skipIfCompleted

  const watch = await appConfirm(message, {
    title: '安装完成',
    confirmText: '观看教程',
    cancelText: '稍后再说',
  })
  if (!watch) return 'dismissed'

  const started = await launchAdvancedDriverTour({ router, buildContext, returnContext })
  return started ? 'started' : 'dismissed'
}

export function resolveRouteNameFromPath(router: Router, path: string): string {
  const raw = String(path || '').trim()
  if (!raw) return 'chat'
  try {
    const resolved = router.resolve(raw)
    return String(resolved.name || 'chat')
  } catch {
    return 'chat'
  }
}
