import { describe, it, expect } from 'vitest'
import {
  manifestToNodes,
  manifestToEdges,
  applyEdgeToManifest,
  addModuleToManifest,
  removeModuleFromManifest,
  MODULE_META,
} from '../../../composables/useWorkbenchManifest'
import { createEmptyEmployeeConfigV2 } from '../../../employeeConfigV2'

describe('useWorkbenchManifest', () => {
  describe('manifestToNodes', () => {
    it('always produces identity and workflow_heart nodes (required)', () => {
      const manifest = createEmptyEmployeeConfigV2() as Record<string, unknown>
      const nodes = manifestToNodes(manifest)
      const kinds = nodes.map((n) => n.data.moduleKind)
      expect(kinds).toContain('identity')
      expect(kinds).toContain('workflow_heart')
    })

    it('does not produce optional nodes when absent from manifest', () => {
      const manifest = { identity: { id: 'x', name: 'x', version: '1.0.0', artifact: 'employee_pack' }, collaboration: { workflow: { workflow_id: 1 } } } as Record<string, unknown>
      const nodes = manifestToNodes(manifest)
      const kinds = nodes.map((n) => n.data.moduleKind)
      expect(kinds).not.toContain('memory')
      expect(kinds).not.toContain('voice')
    })

    it('includes memory node when manifest has memory field', () => {
      const manifest = createEmptyEmployeeConfigV2() as Record<string, unknown>
      manifest.memory = { short_term: { context_window: 8000 } }
      const nodes = manifestToNodes(manifest)
      const kinds = nodes.map((n) => n.data.moduleKind)
      expect(kinds).toContain('memory')
    })

    it('includes voice node with multi-path slice when audio or voice output exists', () => {
      const manifest = createEmptyEmployeeConfigV2() as Record<string, unknown>
      manifest.perception = { audio: { enabled: true } }
      manifest.actions = { voice_output: { enabled: true } }
      const voiceNode = manifestToNodes(manifest).find((n) => n.data.moduleKind === 'voice')
      expect(voiceNode).toBeDefined()
      expect(voiceNode?.data.slice).toMatchObject({
        'perception.audio': { enabled: true },
        'actions.voice_output': { enabled: true },
      })
    })
  })

  describe('manifestToEdges', () => {
    it('generates edges between identity → workflow_heart → prompt', () => {
      const manifest = createEmptyEmployeeConfigV2() as Record<string, unknown>
      manifest.cognition = {
        agent: { system_prompt: 'test', role: { name: '', tone: 'professional', persona: '', expertise: [] }, behavior_rules: [], few_shot_examples: [], model: {} },
        skills: [],
      }
      const nodes = manifestToNodes(manifest)
      const edges = manifestToEdges(nodes)
      const edgePairs = edges.map((e) => `${e.source}→${e.target}`)
      expect(edgePairs).toContain('emp-identity→emp-workflow_heart')
    })

    it('skips edge if a required node is missing', () => {
      // Only identity, no workflow_heart, no prompt
      const manifest = { identity: { id: 'x', name: 'x', version: '1.0.0', artifact: 'employee_pack' } } as Record<string, unknown>
      // Manually create minimal node list
      const nodes = [{ id: 'emp-identity', type: 'employeeModule', position: { x: 0, y: 0 }, data: { moduleKind: 'identity', label: '身份', meta: MODULE_META.identity, slice: null, enabled: true } }]
      const edges = manifestToEdges(nodes)
      expect(edges.length).toBe(0)
    })
  })

  describe('applyEdgeToManifest', () => {
    it('returns manifest unchanged for informational edges', () => {
      const manifest = createEmptyEmployeeConfigV2() as Record<string, unknown>
      expect(applyEdgeToManifest(manifest, 'emp-identity', 'emp-prompt')).toBe(manifest)
    })
  })

  describe('addModuleToManifest', () => {
    it('adds memory module with default structure', () => {
      const manifest = createEmptyEmployeeConfigV2() as Record<string, unknown>
      const next = addModuleToManifest(manifest, 'memory')
      expect(next.memory).toBeDefined()
      expect((next.memory as Record<string, unknown>).short_term).toBeDefined()
    })

    it('does not remove existing modules when adding a new one', () => {
      const manifest = createEmptyEmployeeConfigV2() as Record<string, unknown>
      manifest.memory = { existing: true }
      const next = addModuleToManifest(manifest, 'actions')
      expect((next.memory as Record<string, unknown>).existing).toBe(true)
    })

    it('adds perception, voice, management, and collaboration defaults', () => {
      const manifest = createEmptyEmployeeConfigV2() as Record<string, unknown>
      const withPerception = addModuleToManifest(manifest, 'perception')
      expect(withPerception.perception).toMatchObject({ vision: { enabled: false } })

      const withVoice = addModuleToManifest({ perception: { document: { enabled: true } }, actions: { text_output: { enabled: true } } }, 'voice')
      expect((withVoice.perception as any).audio.asr.languages).toContain('zh-CN')
      expect((withVoice.actions as any).voice_output.tts.provider).toBe('aliyun')

      const withManagement = addModuleToManifest({}, 'management')
      expect((withManagement.management as any).error_handling.retry_policy.max_retries).toBe(3)

      const withCollaboration = addModuleToManifest({ collaboration: { workflow: { id: 1 } } }, 'collaboration')
      expect((withCollaboration.collaboration as any).permissions.access_level).toBe('read_write')
    })
  })

  describe('removeModuleFromManifest', () => {
    it('removes optional memory module', () => {
      const manifest = createEmptyEmployeeConfigV2() as Record<string, unknown>
      manifest.memory = { short_term: { context_window: 8000 } }
      const next = removeModuleFromManifest(manifest, 'memory')
      expect(next.memory).toBeUndefined()
    })

    it('cannot remove required modules (identity, workflow_heart)', () => {
      const manifest = createEmptyEmployeeConfigV2() as Record<string, unknown>
      const next = removeModuleFromManifest(manifest, 'identity')
      expect(next.identity).toBeDefined()
    })

    it('removes voice, perception, actions, management, and collaboration modules', () => {
      const manifest = {
        perception: { audio: { enabled: true }, document: { enabled: true } },
        actions: { voice_output: { enabled: true }, text_output: { enabled: true } },
        management: { enabled: true },
        collaboration: { permissions: { access_level: 'read_write' }, workflow: { id: 1 } },
      } as Record<string, unknown>

      const withoutVoice = removeModuleFromManifest(manifest, 'voice')
      expect((withoutVoice.perception as any).audio).toBeUndefined()
      expect((withoutVoice.actions as any).voice_output).toBeUndefined()

      expect(removeModuleFromManifest(manifest, 'perception').perception).toBeUndefined()
      expect(removeModuleFromManifest(manifest, 'actions').actions).toBeUndefined()
      expect(removeModuleFromManifest(manifest, 'management').management).toBeUndefined()
      expect((removeModuleFromManifest(manifest, 'collaboration').collaboration as any).permissions).toBeUndefined()

      const voiceOnly = removeModuleFromManifest({
        perception: { audio: { enabled: true } },
        actions: { voice_output: { enabled: true } },
      }, 'voice')
      expect(voiceOnly.perception).toBeUndefined()
      expect(voiceOnly.actions).toBeUndefined()
    })
  })
})
