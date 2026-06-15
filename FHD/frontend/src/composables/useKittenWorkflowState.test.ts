import { describe, it, expect } from 'vitest'
import { ref } from 'vue'
import {
  KITTEN_PHASE,
  mapKittenPhaseToStepIndex,
  mapKittenPhaseToLayer,
  useKittenWorkflowState,
  type KittenPhase,
} from './useKittenWorkflowState'

describe('useKittenWorkflowState', () => {
  describe('mapKittenPhaseToStepIndex', () => {
    it('returns 0 for idle phase', () => {
      expect(mapKittenPhaseToStepIndex('idle', false)).toBe(0)
    })

    it('returns 0 for ingesting phase', () => {
      expect(mapKittenPhaseToStepIndex('ingesting', false)).toBe(0)
    })

    it('returns 1 for schemaReady phase', () => {
      expect(mapKittenPhaseToStepIndex('schemaReady', false)).toBe(1)
    })

    it('returns 2 for analyzing phase', () => {
      expect(mapKittenPhaseToStepIndex('analyzing', false)).toBe(2)
    })

    it('returns 3 for delivered phase with dataset', () => {
      expect(mapKittenPhaseToStepIndex('delivered', true)).toBe(3)
    })

    it('returns 2 for delivered phase without dataset', () => {
      expect(mapKittenPhaseToStepIndex('delivered', false)).toBe(2)
    })

    it('returns 2 for error phase', () => {
      expect(mapKittenPhaseToStepIndex('error', false)).toBe(2)
    })
  })

  describe('mapKittenPhaseToLayer', () => {
    it('returns ingest for idle phase', () => {
      expect(mapKittenPhaseToLayer('idle', false)).toBe('ingest')
    })

    it('returns ingest for ingesting phase', () => {
      expect(mapKittenPhaseToLayer('ingesting', false)).toBe('ingest')
    })

    it('returns schema for schemaReady phase', () => {
      expect(mapKittenPhaseToLayer('schemaReady', false)).toBe('schema')
    })

    it('returns analyze for analyzing phase', () => {
      expect(mapKittenPhaseToLayer('analyzing', false)).toBe('analyze')
    })

    it('returns analyze for error phase', () => {
      expect(mapKittenPhaseToLayer('error', false)).toBe('analyze')
    })

    it('returns deliver for delivered phase with dataset', () => {
      expect(mapKittenPhaseToLayer('delivered', true)).toBe('deliver')
    })

    it('returns analyze for delivered phase without dataset', () => {
      expect(mapKittenPhaseToLayer('delivered', false)).toBe('analyze')
    })
  })

  describe('useKittenWorkflowState composable', () => {
    it('returns activeStepIndex and activeLayerKey', () => {
      const phase = ref<KittenPhase>('idle')
      const hasDataset = ref(false)
      const state = useKittenWorkflowState(phase, hasDataset)
      expect(state.activeStepIndex.value).toBe(0)
      expect(state.activeLayerKey.value).toBe('ingest')
    })

    it('reacts to phase changes', () => {
      const phase = ref<KittenPhase>('idle')
      const hasDataset = ref(false)
      const state = useKittenWorkflowState(phase, hasDataset)
      phase.value = 'analyzing'
      expect(state.activeStepIndex.value).toBe(2)
      expect(state.activeLayerKey.value).toBe('analyze')
    })

    it('reacts to hasDataset changes', () => {
      const phase = ref<KittenPhase>('delivered')
      const hasDataset = ref(false)
      const state = useKittenWorkflowState(phase, hasDataset)
      expect(state.activeStepIndex.value).toBe(2)
      hasDataset.value = true
      expect(state.activeStepIndex.value).toBe(3)
      expect(state.activeLayerKey.value).toBe('deliver')
    })
  })

  describe('KITTEN_PHASE constants', () => {
    it('has all expected phases', () => {
      expect(KITTEN_PHASE.idle).toBe('idle')
      expect(KITTEN_PHASE.ingesting).toBe('ingesting')
      expect(KITTEN_PHASE.schemaReady).toBe('schemaReady')
      expect(KITTEN_PHASE.analyzing).toBe('analyzing')
      expect(KITTEN_PHASE.delivered).toBe('delivered')
      expect(KITTEN_PHASE.error).toBe('error')
    })
  })
})
