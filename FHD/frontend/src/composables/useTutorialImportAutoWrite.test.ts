import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

import { useTutorialV2Store } from '@/stores/tutorialV2'
import type { TutorialRunDTO } from '@/api/tutorialV2'
import { useTutorialImportAutoWrite } from './useTutorialImportAutoWrite'

function tutorialRun(courseId: string, status: TutorialRunDTO['status']): TutorialRunDTO {
  return {
    id: 'run-1',
    workspace_id: 'workspace-1',
    course_id: courseId,
    version: 2,
    status,
    current_step_id: null,
    attempt_count: 0,
    progress: 0,
    completed_steps: 0,
    total_steps: 1,
    generation: 1,
    teaching_space: true,
    steps: [],
    started_at: '2026-08-13T00:00:00',
    completed_at: null,
  }
}

describe('useTutorialImportAutoWrite', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('disables automatic writes only during an active data-import course', async () => {
    const store = useTutorialV2Store()
    store.currentRun = tutorialRun('data-import', 'active')

    const enabled = useTutorialImportAutoWrite()
    expect(enabled.value).toBe(false)

    store.currentRun = tutorialRun('data-import', 'paused')
    await nextTick()
    expect(enabled.value).toBe(true)

    store.currentRun = tutorialRun('master-data', 'active')
    await nextTick()
    expect(enabled.value).toBe(true)
  })
})
