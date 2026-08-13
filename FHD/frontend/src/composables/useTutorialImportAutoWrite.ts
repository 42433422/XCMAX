import { ref, watch, type Ref } from 'vue'
import { useTutorialV2Store } from '@/stores/tutorialV2'

export function useTutorialImportAutoWrite(): Ref<boolean> {
  const tutorialStore = useTutorialV2Store()
  const enabled = ref(true)
  watch(
    () => [tutorialStore.currentRun?.course_id, tutorialStore.currentRun?.status],
    ([courseId, status]) => {
      enabled.value = !(courseId === 'data-import' && status === 'active')
    },
    { immediate: true },
  )
  return enabled
}
