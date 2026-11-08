import { computed, type Ref } from 'vue'

export const KITTEN_PHASE = {
  idle: 'idle',
  ingesting: 'ingesting',
  schemaReady: 'schemaReady',
  analyzing: 'analyzing',
  waitingAuthorization: 'waiting_authorization',
  waitingApproval: 'waiting_approval',
  waitingUser: 'waiting_user',
  unknown: 'unknown',
  delivered: 'delivered',
  error: 'error',
} as const

export type KittenPhase = (typeof KITTEN_PHASE)[keyof typeof KITTEN_PHASE]

export const mapKittenPhaseToStepIndex = (phase: KittenPhase, hasDataset: boolean): number => {
  if (phase === KITTEN_PHASE.idle) return 0
  if (phase === KITTEN_PHASE.ingesting) return 0
  if (phase === KITTEN_PHASE.schemaReady) return 1
  if (
    [
      KITTEN_PHASE.analyzing,
      KITTEN_PHASE.waitingAuthorization,
      KITTEN_PHASE.waitingApproval,
      KITTEN_PHASE.waitingUser,
      KITTEN_PHASE.unknown,
    ].some((value) => value === phase)
  )
    return 2
  if (phase === KITTEN_PHASE.delivered) return hasDataset ? 3 : 2
  if (phase === KITTEN_PHASE.error) return 2
  return 0
}

export const mapKittenPhaseToLayer = (phase: KittenPhase, hasDataset: boolean): string => {
  if (phase === KITTEN_PHASE.idle || phase === KITTEN_PHASE.ingesting) return 'ingest'
  if (phase === KITTEN_PHASE.schemaReady) return 'schema'
  if (
    [
      KITTEN_PHASE.analyzing,
      KITTEN_PHASE.error,
      KITTEN_PHASE.waitingAuthorization,
      KITTEN_PHASE.waitingApproval,
      KITTEN_PHASE.waitingUser,
      KITTEN_PHASE.unknown,
    ].some((value) => value === phase)
  )
    return 'analyze'
  if (phase === KITTEN_PHASE.delivered) return hasDataset ? 'deliver' : 'analyze'
  return 'ingest'
}

export const useKittenWorkflowState = (phase: Ref<KittenPhase>, hasDataset: Ref<boolean>) => {
  const activeStepIndex = computed(() => mapKittenPhaseToStepIndex(phase.value, hasDataset.value))
  const activeLayerKey = computed(() => mapKittenPhaseToLayer(phase.value, hasDataset.value))
  return {
    activeStepIndex,
    activeLayerKey,
  }
}
