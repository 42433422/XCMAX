import { describe, expect, it } from 'vitest'
import {
  applyEmployeeDraftPipelineEvent,
  makeStages,
  makePipelineStatus,
  makeStageState,
} from './employeeDraftPipeline'
import { ref } from 'vue'

describe('makeStageState', () => {
  it('returns idle state with defaults', () => {
    const state = makeStageState()
    expect(state.status).toBe('idle')
    expect(state.data).toBeNull()
    expect(state.error).toBe('')
    expect(state.warnings).toEqual([])
  })
})

describe('makeStages', () => {
  it('returns all six stages in idle state', () => {
    const stages = makeStages()
    expect(stages.parse_intent.status).toBe('idle')
    expect(stages.resolve_workflow.status).toBe('idle')
    expect(stages.design_v2.status).toBe('idle')
    expect(stages.suggest_skills.status).toBe('idle')
    expect(stages.suggest_pricing.status).toBe('idle')
    expect(stages.assemble.status).toBe('idle')
  })
})

describe('makePipelineStatus', () => {
  it('returns idle pipeline status', () => {
    const status = makePipelineStatus()
    expect(status.phase).toBe('idle')
    expect(status.current).toBe('')
    expect(status.manifest).toBeNull()
    expect(status.fatalError).toBe('')
  })
})

describe('applyEmployeeDraftPipelineEvent', () => {
  it('stage_start sets stage to running and updates current', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'stage_start',
      stage: 'parse_intent',
    })

    expect(stages.parse_intent.status).toBe('running')
    expect(status.current).toBe('parse_intent')
  })

  it('stage_progress appends message', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'stage_progress',
      stage: 'parse_intent',
      message: 'Analyzing intent...',
    })

    expect(messages.value).toContain('Analyzing intent...')
  })

  it('stage_progress ignores non-string message', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'stage_progress',
      stage: 'parse_intent',
      message: 42,
    })

    expect(messages.value).toHaveLength(0)
  })

  it('stage_done sets stage to done with data and warnings', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])
    const data = { id: 'emp1', name: 'Test', role: 'assistant', scenario: 'test', industry: 'tech', complexity: 'low' }

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'stage_done',
      stage: 'parse_intent',
      data,
      warnings: ['minor issue'],
    })

    expect(stages.parse_intent.status).toBe('done')
    expect(stages.parse_intent.data).toEqual(data)
    expect(stages.parse_intent.warnings).toEqual(['minor issue'])
  })

  it('stage_done handles missing warnings', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'stage_done',
      stage: 'parse_intent',
      data: null,
    })

    expect(stages.parse_intent.warnings).toEqual([])
  })

  it('stage_error sets stage to error', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'stage_error',
      stage: 'parse_intent',
      error: 'Failed to parse',
    })

    expect(stages.parse_intent.status).toBe('error')
    expect(stages.parse_intent.error).toBe('Failed to parse')
  })

  it('stage_error sets fatal error for non-retryable non-optional stages', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'stage_error',
      stage: 'parse_intent',
      error: 'Fatal failure',
      retryable: false,
    })

    expect(status.phase).toBe('error')
    expect(status.fatalError).toBe('Fatal failure')
  })

  it('stage_error does not set fatal for suggest_skills', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'stage_error',
      stage: 'suggest_skills',
      error: 'Skills unavailable',
      retryable: false,
    })

    expect(status.phase).toBe('idle')
  })

  it('stage_error does not set fatal for suggest_pricing', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'stage_error',
      stage: 'suggest_pricing',
      error: 'Pricing unavailable',
      retryable: false,
    })

    expect(status.phase).toBe('idle')
  })

  it('stage_error does not set fatal when retryable', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'stage_error',
      stage: 'parse_intent',
      error: 'Temporary failure',
      retryable: true,
    })

    expect(status.phase).toBe('idle')
  })

  it('pipeline_done sets phase to done with manifest', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])
    const manifest = { identity: { id: 'emp1' } }

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'pipeline_done',
      manifest,
    })

    expect(status.phase).toBe('done')
    expect(status.manifest).toEqual(manifest)
  })

  it('pipeline_error sets phase to error', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'pipeline_error',
      error: 'Init failed',
    })

    expect(status.phase).toBe('error')
    expect(status.fatalError).toBe('Init failed')
  })

  it('pipeline_error uses default error message', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'pipeline_error',
    })

    expect(status.fatalError).toBe('初始化失败')
  })

  it('ignores unknown event types', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'unknown_event',
      stage: 'parse_intent',
    })

    expect(stages.parse_intent.status).toBe('idle')
    expect(status.phase).toBe('idle')
  })

  it('stage_start for unknown stage updates current but not stage status', () => {
    const stages = makeStages()
    const status = makePipelineStatus()
    const messages = ref<string[]>([])

    applyEmployeeDraftPipelineEvent(stages, status, messages, {
      event: 'stage_start',
      stage: 'unknown_stage',
    })

    expect(status.current).toBe('unknown_stage')
  })
})
