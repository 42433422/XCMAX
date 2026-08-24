import { describe, expect, it } from 'vitest'
import { ONBOARDING_INDUSTRY_CATEGORIES, ONBOARDING_INDUSTRY_OPTIONS } from './onboardingIndustryCatalog'
import { resolveIndustryNavigationProfile } from './industryNavigationProfiles'
import {
  buildIndustryTemplateScopeConfig,
  resolveIndustryTemplateProfile,
} from './industryTemplateProfiles'

const menuKeyByScope = {
  products: 'products',
  materials: 'materials',
  customers: 'customers',
  orders: 'orders',
  shipmentRecords: 'shipment-records',
} as const

describe('industry template profiles', () => {
  it('derives all nine industry template catalogs from their real sidebar skeletons', () => {
    for (const category of ONBOARDING_INDUSTRY_CATEGORIES) {
      const templateProfile = resolveIndustryTemplateProfile(category.id)
      const navigation = resolveIndustryNavigationProfile(category.id)

      expect(templateProfile.categoryId).toBe(category.id)
      expect(templateProfile.scopes.length).toBeGreaterThanOrEqual(4)
      expect(new Set(templateProfile.scopes.map((scope) => scope.key)).size).toBe(templateProfile.scopes.length)
      for (const scope of templateProfile.scopes) {
        expect(navigation.previewMenuKeys).toContain(menuKeyByScope[scope.key])
        expect(scope.requiredTerms.length).toBeGreaterThan(0)
      }
    }
  })

  it('resolves every onboarding industry option and the generic industry without fixed sales-only tabs', () => {
    for (const industryId of ['通用', ...ONBOARDING_INDUSTRY_OPTIONS.map((option) => option.id)]) {
      const profile = resolveIndustryTemplateProfile(industryId)
      const config = buildIndustryTemplateScopeConfig(profile)
      expect(Object.keys(config)).toEqual(profile.scopes.map((scope) => scope.key))
      expect(Object.keys(config)).not.toEqual(expect.arrayContaining(['shipmentSummary', 'salesReport']))
    }

    const generic = resolveIndustryTemplateProfile('通用')
    expect(generic.scopes.map((scope) => scope.label)).toEqual(
      expect.arrayContaining(['业务对象', '组织管理', '业务单据', '业务记录']),
    )
    expect(generic.scopes.map((scope) => scope.label)).not.toContain('原材料仓库')
    expect(generic.scopes.map((scope) => scope.templateType)).toEqual(
      expect.arrayContaining(['业务对象', '组织管理', '业务单据', '业务记录']),
    )
  })

  it('uses the actual industry subsystem fields instead of repainting generic required terms', () => {
    const attendance = resolveIndustryTemplateProfile('考勤', {
      config: {
        subsystems: {
          products: {
            label: '人员管理',
            entity: '人员',
            fields: [
              { key: 'model_number', label: '工号' },
              { key: 'name', label: '姓名' },
              { key: 'specification', label: '班次' },
            ],
          },
          orders: {
            label: '考勤单',
            entity: '考勤单',
            fields: [
              { key: 'purchase_unit', label: '部门' },
              { key: 'quantity_kg', label: '工时 (小时)' },
            ],
          },
        },
      },
    })

    const products = attendance.scopes.find((scope) => scope.key === 'products')
    const orders = attendance.scopes.find((scope) => scope.key === 'orders')
    expect(products).toMatchObject({
      label: '人员管理',
      templateType: '人员',
      requiredTerms: ['工号', '姓名', '班次'],
      schemaSource: 'industry-subsystem',
    })
    expect(orders).toMatchObject({
      label: '考勤单',
      requiredTerms: ['部门', '工时 (小时)'],
      schemaSource: 'industry-subsystem',
    })
    expect(attendance.scopes.map((scope) => scope.key)).toEqual(['products', 'orders'])
  })

  it('keeps coating and software catalogs distinct', () => {
    const coating = resolveIndustryTemplateProfile('涂料')
    const software = resolveIndustryTemplateProfile('软件信息')

    expect(coating.scopes.map((scope) => scope.label)).toEqual(
      expect.arrayContaining(['产品管理', '原材料仓库', '出货单管理', '出货记录', '客户管理']),
    )
    expect(software.scopes.map((scope) => scope.label)).toEqual(
      expect.arrayContaining(['服务产品', '服务订单', '交付记录', '客户管理']),
    )
    expect(software.scopes.some((scope) => scope.key === 'materials')).toBe(false)
  })
})
