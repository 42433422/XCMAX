import { beforeEach, describe, expect, it } from 'vitest'
import { ALL_SKILLS, buildSkillSystemPrompt, loadActiveSkills, saveActiveSkills } from './chatSkills'

describe('chatSkills', () => {
  beforeEach(() => {
    if (typeof localStorage !== 'undefined') localStorage.clear()
  })

  it('exposes the canonical skill list', () => {
    expect(ALL_SKILLS.map((s) => s.id)).toEqual(['web', 'think', 'translate', 'write', 'code', 'data', 'study'])
  })

  it('builds system prompt only for active skills', () => {
    const empty = buildSkillSystemPrompt([])
    expect(empty).toBe('')
    const web = buildSkillSystemPrompt(['web'])
    expect(web).toContain('联网搜索')
    expect(web).not.toContain('深度思考')
    const both = buildSkillSystemPrompt(['web', 'think'])
    expect(both).toContain('联网搜索')
    expect(both).toContain('深度思考')
  })

  it('persists active skills to localStorage', () => {
    saveActiveSkills(['code', 'data'])
    expect(loadActiveSkills().sort()).toEqual(['code', 'data'])
  })

  it('returns empty array when storage corrupted', () => {
    localStorage.setItem('workbench_direct_skills_v1', 'not-json')
    expect(loadActiveSkills()).toEqual([])
  })
})
