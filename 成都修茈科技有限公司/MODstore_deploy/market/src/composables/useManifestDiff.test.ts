import { describe, expect, it, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useWorkbenchStore } from '../stores/workbench'
import { useManifestDiff } from './useManifestDiff'

describe('useManifestDiff', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
  })

  it('hasBaseline is false when no baseline stored', () => {
    const store = useWorkbenchStore()
    store.setTarget('employee', 'emp1', { identity: { name: 'Test' } }, 'Test')
    const { hasBaseline, diffs, diffCount, hasDiff } = useManifestDiff()
    expect(hasBaseline.value).toBe(false)
    expect(diffs.value).toEqual([])
    expect(diffCount.value).toBe(0)
    expect(hasDiff.value).toBe(false)
  })

  it('detects changes when baseline differs from current', () => {
    const store = useWorkbenchStore()
    store.setTarget('employee', 'emp1', {
      identity: { name: 'Original', id: 'emp1', version: '1.0.0' },
    }, 'Original')

    sessionStorage.setItem('workbench_baseline_manifest_emp1', JSON.stringify({
      identity: { name: 'Original', id: 'emp1', version: '1.0.0' },
    }))

    store.patchManifest('identity.name', 'Changed')

    const { hasBaseline, diffs, diffCount, hasDiff } = useManifestDiff()
    expect(hasBaseline.value).toBe(true)
    expect(diffCount.value).toBeGreaterThan(0)
    expect(hasDiff.value).toBe(true)

    const nameDiff = diffs.value.find((d) => d.path === 'identity.name')
    expect(nameDiff).toBeDefined()
    expect(nameDiff!.before).toBe('Original')
    expect(nameDiff!.after).toBe('Changed')
  })

  it('shows no diff when baseline matches current', () => {
    const store = useWorkbenchStore()
    const manifest = { identity: { name: 'Same', id: 'emp1', version: '1.0.0' } }
    store.setTarget('employee', 'emp1', manifest, 'Same')

    sessionStorage.setItem('workbench_baseline_manifest_emp1', JSON.stringify(manifest))

    const { hasBaseline, diffs, hasDiff } = useManifestDiff()
    expect(hasBaseline.value).toBe(true)
    expect(hasDiff.value).toBe(false)
    expect(diffs.value).toEqual([])
  })

  it('hasBaseline is false when target has no id', () => {
    const store = useWorkbenchStore()
    store.setTarget('employee', null, {}, 'No ID')

    const { hasBaseline } = useManifestDiff()
    expect(hasBaseline.value).toBe(false)
  })

  it('handles invalid JSON in sessionStorage gracefully', () => {
    const store = useWorkbenchStore()
    store.setTarget('employee', 'emp1', { identity: { name: 'Test' } }, 'Test')
    sessionStorage.setItem('workbench_baseline_manifest_emp1', 'not-json')

    const { hasBaseline } = useManifestDiff()
    expect(hasBaseline.value).toBe(false)
  })

  it('detects changes in cognition.agent.system_prompt', () => {
    const store = useWorkbenchStore()
    store.setTarget('employee', 'emp1', {
      identity: { name: 'Test' },
      cognition: { agent: { system_prompt: 'Original prompt' } },
    }, 'Test')

    sessionStorage.setItem('workbench_baseline_manifest_emp1', JSON.stringify({
      identity: { name: 'Test' },
      cognition: { agent: { system_prompt: 'Original prompt' } },
    }))

    store.patchManifest('cognition.agent.system_prompt', 'New prompt')

    const { diffs } = useManifestDiff()
    const promptDiff = diffs.value.find((d) => d.path === 'cognition.agent.system_prompt')
    expect(promptDiff).toBeDefined()
    expect(promptDiff!.label).toBe('System Prompt')
  })
})
