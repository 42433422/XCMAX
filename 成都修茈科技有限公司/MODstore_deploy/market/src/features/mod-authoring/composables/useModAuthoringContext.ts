import { inject, provide, type InjectionKey } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useModAuthoring } from './useModAuthoring'

export type ModAuthoringContext = ReturnType<typeof useModAuthoring>

export const ModAuthoringKey: InjectionKey<ModAuthoringContext> = Symbol('modAuthoring')

export function provideModAuthoring(): ModAuthoringContext {
  const route = useRoute()
  const router = useRouter()
  const ctx = useModAuthoring(route, router)
  provide(ModAuthoringKey, ctx)
  return ctx
}

export function useModAuthoringContext(): ModAuthoringContext {
  const ctx = inject(ModAuthoringKey)
  if (!ctx) {
    throw new Error('useModAuthoringContext() must be used within ModAuthoringPage')
  }
  return ctx
}
