import { describe, it, expect } from 'vitest'
import {
  manifestToNodes,
  manifestToEdges,
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
  })
})
