import { describe, it, expect } from 'vitest'
import {
  buildEnterpriseModStack,
  modBelongsToEnterpriseStack,
  isWorkflowCarrierModId,
} from './enterpriseModStack'
import type { IndustryBaselinePlan } from '@/constants/platformShell'

describe('enterpriseModStack', () => {
  const plan: IndustryBaselinePlan = {
    industry_id: '涂料',
    industry_package: { mod_id: 'coating-industry', product_name: '涂料行业包' },
    groups: [
      {
        id: 'account_custom',
        title: '账号定制',
        hint: '',
        items: [
          {
            mod_id: 'sz-qsm-pro',
            label: '奇士美定制',
            tier: 'account_custom',
            required: true,
            installed: false,
          },
        ],
      },
    ],
    required_mod_ids: ['xcagi-core-workflow-employees', 'xcagi-erp-domain-bridge'],
    optional_mod_ids: ['wechat-contacts-ai-employee'],
    industry_mod_ids: ['coating-industry'],
    account_custom_mod_ids: ['sz-qsm-pro'],
    custom_mod_ids: ['coating-industry', 'sz-qsm-pro'],
    missing_required_mod_ids: [],
    missing_optional_mod_ids: [],
    missing_industry_mod_ids: [],
    baseline_ready: true,
    industry_mod_ready: true,
  }

  it('builds stack label from industry + custom mods', () => {
    const stack = buildEnterpriseModStack(plan)
    expect(stack.stackLabel).toContain('涂料行业包')
    expect(stack.stackLabel).toContain('奇士美定制')
    expect(stack.packageModIds).toContain('coating-industry')
    expect(stack.packageModIds).toContain('sz-qsm-pro')
  })

  it('recognizes package mods and host line without custom-phase carriers', () => {
    const stack = buildEnterpriseModStack(plan)
    expect(isWorkflowCarrierModId('xcagi-workflow-employee-label-print')).toBe(true)
    expect(isWorkflowCarrierModId('xcagi-core-workflow-employees')).toBe(false)
    expect(modBelongsToEnterpriseStack('coating-industry', stack)).toBe(true)
    expect(modBelongsToEnterpriseStack('sz-qsm-pro', stack)).toBe(true)
    expect(modBelongsToEnterpriseStack('xcagi-core-workflow-employees', stack)).toBe(true)
    expect(modBelongsToEnterpriseStack('random-mod', stack)).toBe(false)
  })
})
