import { useOnboardingTutorialStore } from '@/stores/onboardingTutorial'

/** Driver 快速上手教程是否正在运行 */
export function isOnboardingDriverTutorialActive(): boolean {
  try {
    if (useOnboardingTutorialStore().active) return true
  } catch {
    /* pinia 未就绪时回退 DOM 标记 */
  }
  return typeof document !== 'undefined' && document.body.classList.contains('tutorial-active')
}
