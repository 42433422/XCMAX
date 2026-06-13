import { nextTick } from 'vue'
import type { Router } from 'vue-router'
import { appConfirm } from '@/utils/appDialog'
import { useOnboardingTutorialStore } from '@/stores/onboardingTutorial'
import type { OnboardingReturnContext } from '@/stores/onboardingTutorial'
import type { TutorialBuildContext } from '@/tutorial/types'

const DEFAULT_INSTALL_MESSAGE =
  '安装已完成，可以开始使用了。\n\n是否现在观看进阶教程，快速熟悉菜单与智能对话？'

export async function launchAdvancedDriverTour(options: {
  router: Router
  buildContext: TutorialBuildContext
  returnContext?: OnboardingReturnContext
  skipNavigation?: boolean
}): Promise<boolean> {
  const store = useOnboardingTutorialStore()
  const { router, buildContext, returnContext, skipNavigation = false } = options

  if (!skipNavigation) {
    await router.push({ name: 'chat' }).catch(() => {})
    await nextTick()

    for (let i = 0; i < 4; i += 1) {
      const newConversationBtn = document.getElementById('newConversationBtn')
      if (newConversationBtn) {
        newConversationBtn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
        break
      }
      await new Promise((resolve) => window.setTimeout(resolve, 80))
    }
  }

  store.start({
    track: 'advanced',
    buildContext,
    returnContext: returnContext ?? { routeName: 'chat' },
  })
  return store.active
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

  const store = useOnboardingTutorialStore()
  if (skipIfCompleted && store.isCompleted()) {
    return 'already_completed'
  }

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
