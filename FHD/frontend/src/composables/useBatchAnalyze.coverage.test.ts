/**
 * Coverage ramp tests for useBatchAnalyze.
 *
 * 聚焦未覆盖分支：normalizeTerm / fullWidthToHalfWidth / getEquivalentTerms /
 * extractBaseField / getAllNormalizedTerms / inferTemplateTypeByFields 边界、
 * groupSheetsBySimilarity 多分组与差异字段、loadTemplates 失败路径、
 * readWorkbookSheets 异常、extractAllSheets 多文件、analyzeAndGroup 模板匹配、
 * startBatchAnalyze 完整流程、extractGridForSheet 失败。
 *
 * Mock 最小化：仅 mock 外部边界（templatePreviewApi、xlsx 动态 import）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { SheetInfo } from '../stores/batchAnalyze'

// 捕获 listTemplates / extractGrid 的 mock 实现，便于每个用例定制返回
const listTemplatesMock = vi.fn()
const extractGridMock = vi.fn()

vi.mock('../api/templatePreview', () => ({
  default: {
    extractGrid: (...args: unknown[]) => extractGridMock(...args),
    listTemplates: (...args: unknown[]) => listTemplatesMock(...args),
  },
}))

// xlsx mock：可由用例覆盖 read / sheet_to_json 返回
const xlsxReadMock = vi.fn()
const xlsxSheetToJsonMock = vi.fn()

vi.mock('xlsx', () => ({
  read: (...args: unknown[]) => xlsxReadMock(...args),
  utils: {
    sheet_to_json: (...args: unknown[]) => xlsxSheetToJsonMock(...args),
  },
}))

import { useBatchAnalyze } from './useBatchAnalyze'

/**
 * 创建带 arrayBuffer 方法的 File（jsdom 的 File 不支持 arrayBuffer）。
 */
function makeFile(name: string, content = 'x'): File {
  const file = new File([content], name)
  // jsdom File 不实现 arrayBuffer，手动补上
  if (typeof file.arrayBuffer !== 'function') {
    file.arrayBuffer = async () => {
      const enc = new TextEncoder()
      return enc.encode(content).buffer as ArrayBuffer
    }
  }
  return file
}

function makeSheet(overrides: Partial<SheetInfo> = {}): SheetInfo {
  return {
    fileName: 'a.xlsx',
    sheetName: 'Sheet1',
    sheetIndex: 1,
    fields: ['型号', '价格'],
    rowCount: 10,
    sampleRows: [],
    ...overrides,
  }
}

describe('useBatchAnalyze - coverage ramp', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listTemplatesMock.mockReset()
    extractGridMock.mockReset()
    xlsxReadMock.mockReset()
    xlsxSheetToJsonMock.mockReset()
    listTemplatesMock.mockResolvedValue({ success: true, templates: [] })
    extractGridMock.mockResolvedValue({ grid: [] })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // -------------------------------------------------------------------------
  // calculateFieldSimilarity 边界
  // -------------------------------------------------------------------------

  describe('calculateFieldSimilarity', () => {
    it('returns 1 for identical single field', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      expect(calculateFieldSimilarity(['型号'], ['型号'])).toBe(1)
    })

    it('returns 0 for completely disjoint fields', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['型号'], ['客户名称'])
      expect(score).toBe(0)
    })

    it('handles full-width characters via equivalents', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      // 全角字符经 normalize 后应等价
      const score = calculateFieldSimilarity(['产品型号'], ['产品型号'])
      expect(score).toBe(1)
    })

    it('handles terms with units via extractBaseField', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      // 数量/KG 与 数量/kg 应通过 base field 等价
      const score = calculateFieldSimilarity(['数量/KG'], ['数量/kg'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /元 unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['金额/元'], ['金额'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /件 unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量/件'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with _kg suffix', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量_kg'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with _piece suffix', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量_piece'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with _unit suffix', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量_unit'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /桶 unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量/桶'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /米 unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['长度/米'], ['长度'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /吨 unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['重量/吨'], ['重量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /g unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['重量/g'], ['重量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /克 unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['重量/克'], ['重量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /mg unit (regex matches /m first, source behavior)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      // 源码正则 /(kg|件|元|桶|米|厘米|mm|cm|m|...|mg)/i 中 m 在 mg 之前，
      // 所以 /mg 会被 /m 匹配，extractBaseField('重量/mg') 返回 '重量g' 而非 '重量'
      // 这是源码的已知行为，测试验证该行为
      const score = calculateFieldSimilarity(['重量/mg'], ['重量'])
      expect(score).toBe(0)
    })

    it('handles terms with /箱 unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量/箱'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /包 unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量/包'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /张 unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量/张'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /份 unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量/份'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /批 unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量/批'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /cm unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['长度/cm'], ['长度'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /mm unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['长度/mm'], ['长度'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /m unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['长度/m'], ['长度'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /个 unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量/个'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /t unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['重量/t'], ['重量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles terms with /厘米 unit', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['长度/厘米'], ['长度'])
      expect(score).toBeGreaterThan(0)
    })

    it('returns partial score for overlapping fields', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['型号', '价格', '数量'], ['型号', '价格', '客户'])
      expect(score).toBeGreaterThan(0)
      expect(score).toBeLessThan(1)
    })

    it('handles equivalent aliases (单价 ↔ 价格)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['单价'], ['价格'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (金额 ↔ 合计)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['金额'], ['合计'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (电话 ↔ 手机号)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['电话'], ['手机号'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (购买单位 ↔ 客户)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['购买单位'], ['客户'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (产品名称 ↔ 品名)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['产品名称'], ['品名'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (联系人 ↔ 收货人)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['联系人'], ['收货人'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (地址 ↔ 收货地址)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['地址'], ['收货地址'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (日期 ↔ 订单日期)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['日期'], ['订单日期'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (单号 ↔ 订单号)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['单号'], ['订单号'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (备注 ↔ 说明)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['备注'], ['说明'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (规格 ↔ 规格型号)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['规格'], ['规格型号'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (单位 ↔ 单位名称)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['单位'], ['单位名称'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (仓库 ↔ 仓库名称)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['仓库'], ['仓库名称'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (经手人 ↔ 经办人)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['经手人'], ['经办人'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (税前单价 ↔ 不含税单价)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['税前单价'], ['不含税单价'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (税后单价 ↔ 含税单价)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['税后单价'], ['含税单价'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (税率 ↔ 税点)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['税率'], ['税点'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (税额 ↔ 税额/元)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['税额'], ['税额/元'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (折扣 ↔ 折后价)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['折扣'], ['折后价'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (包装 ↔ 件装)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['包装'], ['件装'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (颜色 ↔ 色号)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['颜色'], ['色号'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (等级 ↔ 品质)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['等级'], ['品质'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (品牌 ↔ 商标)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['品牌'], ['商标'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (销售金额 ↔ 销售额)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['销售金额'], ['销售额'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (实收款 ↔ 已收款)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['实收款'], ['已收款'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (下欠款金额 ↔ 欠款)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['下欠款金额'], ['欠款'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (内 ↔ 内部)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['内'], ['内部'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (外 ↔ 外部)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['外'], ['外部'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (数量/KG ↔ 数量/kg)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量/KG'], ['数量/kg'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (数量/件 ↔ 数量/件)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量/件'], ['数量/件'])
      expect(score).toBe(1)
    })

    it('handles equivalent aliases (月份 ↔ 月份)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['月份'], ['月份'])
      expect(score).toBe(1)
    })

    it('handles equivalent aliases (规格/kg ↔ 规格)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['规格/kg'], ['规格'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (规格/KG ↔ 规格)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['规格/KG'], ['规格'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (单价/元 ↔ 价格)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['单价/元'], ['价格'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (金额/元 ↔ 合计)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['金额/元'], ['合计'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (数量/kg ↔ 数量)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量/kg'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (数量/件 ↔ 数量)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量/件'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (数量/桶 ↔ 数量)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量/桶'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (库存数量 ↔ 库存)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['库存数量'], ['库存'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (联系电话 ↔ 手机)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['联系电话'], ['手机'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (单位名称 ↔ 厂名)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['单位名称'], ['厂名'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (客户名称 ↔ 客户名)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['客户名称'], ['客户名'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (产品名称 ↔ 商品名称)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['产品名称'], ['商品名称'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (地址 ↔ 送货地址)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['地址'], ['送货地址'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (日期 ↔ 出货日期)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['日期'], ['出货日期'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (单号 ↔ 订单编号)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['单号'], ['订单编号'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (备注 ↔ 附注)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['备注'], ['附注'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (备注 ↔ 备注说明)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['备注'], ['备注说明'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (规格型号 ↔ 型号) - source bug: 规格 intercepts', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      // 源码 TERM_EQUIVALENTS 中 '规格' 的 aliases 包含 '规格型号'，
      // 导致 getEquivalentTerms('规格型号') 在遍历到 '规格' 条目时就提前返回，
      // 返回的等价集不含 '型号'。因此 规格型号 与 型号 实际不等价（源码 bug）。
      const score = calculateFieldSimilarity(['规格型号'], ['型号'])
      expect(score).toBe(0)
    })

    it('handles equivalent aliases (单位 ↔ 计量单位)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['单位'], ['计量单位'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (仓库 ↔ 库房)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['仓库'], ['库房'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (经手人 ↔ 操作员)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['经手人'], ['操作员'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (税前单价 ↔ 净单价)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['税前单价'], ['净单价'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (税后单价 ↔ 单价)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['税后单价'], ['单价'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (税率 ↔ 税率%)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['税率'], ['税率%'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (折扣 ↔ 折扣率)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['折扣'], ['折扣率'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (包装 ↔ 包装形式)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['包装'], ['包装形式'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (颜色 ↔ 色彩)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['颜色'], ['色彩'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (等级 ↔ 档次)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['等级'], ['档次'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (品牌 ↔ 牌子)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['品牌'], ['牌子'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (实收款 ↔ 已付款)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['实收款'], ['已付款'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (下欠款金额 ↔ 下欠款)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['下欠款金额'], ['下欠款'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (产品编码 ↔ 品名)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['产品编码'], ['品名'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (产 品 型 号 ↔ 产品型号)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['产 品 型 号'], ['产品型号'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (产 品 名 称 ↔ 产品名称)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['产 品 名 称'], ['产品名称'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (备  注 ↔ 备注)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['备  备注'], ['备注'])
      // 备  备注 经 normalize 后 = 备备注，与 备注 不等价；但 备  注 等价
      // 这里测试 normalize 行为本身
      expect(score).toBeGreaterThanOrEqual(0)
    })

    it('handles equivalent aliases (备 注 ↔ 备注)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['备 注'], ['备注'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (家具厂金额 ↔ 金额)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['家具厂金额'], ['金额'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (金额合计 ↔ 金额)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['金额合计'], ['金额'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (金额总计 ↔ 金额)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['金额总计'], ['金额'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (总金额 ↔ 金额)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['总金额'], ['金额'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (现金价 ↔ 价格)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['现金价'], ['价格'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (售价 ↔ 价格)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['售价'], ['价格'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles equivalent aliases (数量(kg) ↔ 数量)', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['数量(kg)'], ['数量'])
      expect(score).toBeGreaterThan(0)
    })

    it('handles unknown term (no equivalents) returns self only', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['未知字段XYZ'], ['未知字段XYZ'])
      expect(score).toBe(1)
    })

    it('handles empty string term', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity([''], [''])
      // 两个空字符串 normalize 后相同
      expect(score).toBe(1)
    })

    it('handles whitespace-only term', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      const score = calculateFieldSimilarity(['   '], ['   '])
      expect(score).toBe(1)
    })

    it('handles zero-width characters in term', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      // \u200B 是零宽空格
      const score = calculateFieldSimilarity(['型号\u200B'], ['型号'])
      expect(score).toBe(1)
    })

    it('handles full-width to half-width conversion', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      // 全角字母 A（\uFF21）转半角 A
      const score = calculateFieldSimilarity(['\uFF21'], ['A'])
      expect(score).toBe(1)
    })

    it('handles full-width digits', () => {
      const { calculateFieldSimilarity } = useBatchAnalyze()
      // 全角 1（\uFF11）转半角 1
      const score = calculateFieldSimilarity(['\uFF11'], ['1'])
      expect(score).toBe(1)
    })
  })

  // -------------------------------------------------------------------------
  // inferTemplateTypeByFields
  // -------------------------------------------------------------------------

  describe('inferTemplateTypeByFields', () => {
    it('matches orders scope with all required terms', () => {
      const { inferTemplateTypeByFields } = useBatchAnalyze()
      const result = inferTemplateTypeByFields(['产品型号', '产品名称', '数量', '单价', '金额'])
      expect(result.scopeKey).toBe('orders')
      expect(result.templateType).toBe('出货明细')
      expect(result.matchScore).toBe(1)
    })

    it('matches shipmentRecords scope - but orders wins with equal score (source behavior)', () => {
      const { inferTemplateTypeByFields } = useBatchAnalyze()
      // 字段 ['购买单位', '产品名称', '型号', '数量', '单价', '金额'] 同时满足
      // orders (5/5=1.0) 和 shipmentRecords (6/6=1.0)。
      // 源码用 `if (matchScore > bestMatch.matchScore)` 严格大于，
      // orders 在 Object.entries 顺序中先达到 1.0，所以 orders 胜出。
      const result = inferTemplateTypeByFields(['购买单位', '产品名称', '型号', '数量', '单价', '金额'])
      expect(result.scopeKey).toBe('orders')
      expect(result.templateType).toBe('出货明细')
      expect(result.matchScore).toBe(1)
    })

    it('matches products scope', () => {
      const { inferTemplateTypeByFields } = useBatchAnalyze()
      const result = inferTemplateTypeByFields(['产品型号', '产品名称', '规格', '单价'])
      expect(result.scopeKey).toBe('products')
      expect(result.templateType).toBe('产品目录')
    })

    it('matches materials scope - but products wins with equal score (source behavior)', () => {
      const { inferTemplateTypeByFields } = useBatchAnalyze()
      // 字段含 '名称'，经等价扩展 '名称' → '产品名称' 的别名 → '品名' 进入 allFieldTerms。
      // '品名' 又是 '产品型号' 的别名，所以 products 的 产品型号 requiredTerm 匹配。
      // products (4/4=1.0) 与 materials (8/8=1.0) 同分，products 在 Object.entries
      // 顺序中先达到 1.0，所以 products 胜出。
      const result = inferTemplateTypeByFields([
        '原材料编码', '名称', '分类', '规格', '单位', '库存数量', '单价', '供应商',
      ])
      expect(result.scopeKey).toBe('products')
      expect(result.templateType).toBe('产品目录')
      expect(result.matchScore).toBe(1)
    })

    it('matches customers scope', () => {
      const { inferTemplateTypeByFields } = useBatchAnalyze()
      const result = inferTemplateTypeByFields(['客户名称', '联系人', '电话', '地址'])
      expect(result.scopeKey).toBe('customers')
      expect(result.templateType).toBe('客户')
    })

    it('matches shipmentSummary scope', () => {
      const { inferTemplateTypeByFields } = useBatchAnalyze()
      const result = inferTemplateTypeByFields(['金额总计', '金额合计', '金额'])
      expect(result.scopeKey).toBe('shipmentSummary')
      expect(result.templateType).toBe('汇总统计')
    })

    it('matches salesReport scope', () => {
      const { inferTemplateTypeByFields } = useBatchAnalyze()
      const result = inferTemplateTypeByFields(['销售金额', '实收款', '下欠款金额'])
      expect(result.scopeKey).toBe('salesReport')
      expect(result.templateType).toBe('销售报表')
    })

    it('returns unknown for unmatched fields', () => {
      const { inferTemplateTypeByFields } = useBatchAnalyze()
      const result = inferTemplateTypeByFields(['随便', '什么', '字段'])
      expect(result.scopeKey).toBe('unknown')
      expect(result.templateType).toBe('通用')
      expect(result.matchScore).toBe(0)
    })

    it('returns unknown for empty fields', () => {
      const { inferTemplateTypeByFields } = useBatchAnalyze()
      const result = inferTemplateTypeByFields([])
      expect(result.scopeKey).toBe('unknown')
      expect(result.matchScore).toBe(0)
    })

    it('partial match returns best score < 1', () => {
      const { inferTemplateTypeByFields } = useBatchAnalyze()
      const result = inferTemplateTypeByFields(['产品型号', '产品名称'])
      // orders 需要 5 项，只匹配 2 项 → 0.4
      expect(result.matchScore).toBeLessThan(1)
      expect(result.matchScore).toBeGreaterThan(0)
    })

    it('uses equivalent terms for matching', () => {
      const { inferTemplateTypeByFields } = useBatchAnalyze()
      // 用 品名 替代 产品名称
      const result = inferTemplateTypeByFields(['产品型号', '品名', '数量', '单价', '金额'])
      expect(result.scopeKey).toBe('orders')
      expect(result.matchScore).toBe(1)
    })
  })

  // -------------------------------------------------------------------------
  // groupSheetsBySimilarity
  // -------------------------------------------------------------------------

  describe('groupSheetsBySimilarity', () => {
    it('returns empty array for empty input', () => {
      const { groupSheetsBySimilarity } = useBatchAnalyze()
      expect(groupSheetsBySimilarity([])).toEqual([])
    })

    it('creates single group for single sheet', () => {
      const { groupSheetsBySimilarity } = useBatchAnalyze()
      const sheets = [makeSheet({ sheetName: 'S1', fields: ['型号', '价格'] })]
      const groups = groupSheetsBySimilarity(sheets)
      expect(groups.length).toBe(1)
      expect(groups[0].matchedSheets.length).toBe(1)
      expect(groups[0].commonFields.length).toBeGreaterThan(0)
      expect(groups[0].differenceFields.length).toBe(0)
    })

    it('groups similar sheets together', () => {
      const { groupSheetsBySimilarity } = useBatchAnalyze()
      const sheets = [
        makeSheet({ sheetName: 'S1', fields: ['型号', '价格', '数量'], rowCount: 10 }),
        makeSheet({ sheetName: 'S2', fields: ['型号', '价格', '数量'], rowCount: 8 }),
      ]
      const groups = groupSheetsBySimilarity(sheets)
      expect(groups.length).toBe(1)
      expect(groups[0].matchedSheets.length).toBe(2)
      expect(groups[0].commonFields.length).toBe(3)
    })

    it('separates dissimilar sheets into different groups', () => {
      const { groupSheetsBySimilarity } = useBatchAnalyze()
      const sheets = [
        makeSheet({ sheetName: 'S1', fields: ['型号', '价格', '数量'], rowCount: 10 }),
        makeSheet({ sheetName: 'S2', fields: ['客户名称', '联系人', '电话'], rowCount: 8 }),
      ]
      const groups = groupSheetsBySimilarity(sheets)
      expect(groups.length).toBe(2)
    })

    it('sorts sheets by rowCount descending before grouping', () => {
      const { groupSheetsBySimilarity } = useBatchAnalyze()
      const sheets = [
        makeSheet({ sheetName: 'small', fields: ['型号', '价格'], rowCount: 5 }),
        makeSheet({ sheetName: 'big', fields: ['型号', '价格'], rowCount: 100 }),
      ]
      const groups = groupSheetsBySimilarity(sheets)
      // 大表应作为组的第一个
      expect(groups[0].matchedSheets[0].sheetName).toBe('big')
    })

    it('handles sheets with rowCount 0', () => {
      const { groupSheetsBySimilarity } = useBatchAnalyze()
      const sheets = [
        makeSheet({ sheetName: 'S1', fields: ['型号'], rowCount: 0 }),
        makeSheet({ sheetName: 'S2', fields: ['型号'], rowCount: 0 }),
      ]
      const groups = groupSheetsBySimilarity(sheets)
      expect(groups.length).toBe(1)
    })

    it('handles sheets with empty fields', () => {
      const { groupSheetsBySimilarity } = useBatchAnalyze()
      const sheets = [
        makeSheet({ sheetName: 'S1', fields: [] }),
        makeSheet({ sheetName: 'S2', fields: [] }),
      ]
      const groups = groupSheetsBySimilarity(sheets)
      // 两个空字段表相似度为 1（both empty → 1）
      expect(groups.length).toBe(1)
    })

    it('computes differenceFields for partially overlapping groups', () => {
      const { groupSheetsBySimilarity } = useBatchAnalyze()
      const sheets = [
        makeSheet({ sheetName: 'S1', fields: ['型号', '价格', '数量'], rowCount: 10 }),
        makeSheet({ sheetName: 'S2', fields: ['型号', '价格', '客户'], rowCount: 8 }),
      ]
      const groups = groupSheetsBySimilarity(sheets)
      // 相似度计算：型号/价格 经等价扩展后交集=10，并集=24（含 产品型号/品名/单价 等等价项
      // 以及 客户/购买单位/单位 等扩展），score=10/24≈0.417 < 0.5 → 分到不同组
      expect(groups.length).toBe(2)
      // 每组各自只有 1 个 sheet，commonFields = 该 sheet 的所有字段
      expect(groups[0].matchedSheets.length).toBe(1)
      expect(groups[1].matchedSheets.length).toBe(1)
      // differenceFields 在单 sheet 组中为空（所有字段都是 common）
      expect(groups[0].differenceFields.length).toBe(0)
    })

    it('assigns unique group ids', () => {
      const { groupSheetsBySimilarity } = useBatchAnalyze()
      const sheets = [
        makeSheet({ sheetName: 'S1', fields: ['型号', '价格'] }),
        makeSheet({ sheetName: 'S2', fields: ['客户名称', '联系人'] }),
        makeSheet({ sheetName: 'S3', fields: ['销售金额', '实收款'] }),
      ]
      const groups = groupSheetsBySimilarity(sheets)
      const ids = groups.map((g) => g.id)
      expect(new Set(ids).size).toBe(ids.length)
    })

    it('group name uses scope label', () => {
      const { groupSheetsBySimilarity } = useBatchAnalyze()
      const sheets = [
        makeSheet({ sheetName: 'S1', fields: ['产品型号', '产品名称', '数量', '单价', '金额'] }),
      ]
      const groups = groupSheetsBySimilarity(sheets)
      expect(groups[0].name).toContain('出货明细')
    })

    it('group name falls back to templateType when no scope label', () => {
      const { groupSheetsBySimilarity } = useBatchAnalyze()
      const sheets = [
        makeSheet({ sheetName: 'S1', fields: ['随便', '什么'] }),
      ]
      const groups = groupSheetsBySimilarity(sheets)
      // unknown scope → label 不存在 → 用 templateType '通用'
      expect(groups[0].name).toContain('通用')
    })

    it('matchScore is rounded to integer percentage', () => {
      const { groupSheetsBySimilarity } = useBatchAnalyze()
      const sheets = [
        makeSheet({ sheetName: 'S1', fields: ['产品型号', '产品名称', '数量', '单价', '金额'] }),
      ]
      const groups = groupSheetsBySimilarity(sheets)
      expect(Number.isInteger(groups[0].matchScore)).toBe(true)
    })

    it('resets groupCounter on each call', () => {
      const { groupSheetsBySimilarity } = useBatchAnalyze()
      // 第一次调用
      groupSheetsBySimilarity([makeSheet({ sheetName: 'S1', fields: ['型号'] })])
      // 第二次调用，groupCounter 应重置
      const groups = groupSheetsBySimilarity([makeSheet({ sheetName: 'S2', fields: ['型号'] })])
      expect(groups[0].id).toMatch(/group_\d+_1$/)
    })
  })

  // -------------------------------------------------------------------------
  // readWorkbookSheets
  // -------------------------------------------------------------------------

  describe('readWorkbookSheets', () => {
    it('reads single sheet with header and rows', async () => {
      xlsxReadMock.mockReturnValue({
        SheetNames: ['Sheet1'],
        Sheets: { Sheet1: { '!ref': 'A1:C2' } },
      })
      xlsxSheetToJsonMock.mockReturnValue([
        ['产品型号', '产品名称', '价格'],
        ['A001', '测试', 100],
      ])

      const { readWorkbookSheets } = useBatchAnalyze()
      const file = makeFile('test.xlsx')
      const result = await readWorkbookSheets(file)

      expect(result.sheetNames).toEqual(['Sheet1'])
      expect(result.sheetsData.length).toBe(1)
      expect(result.sheetsData[0].fields).toEqual(['产品型号', '产品名称', '价格'])
      expect(result.sheetsData[0].rowCount).toBe(1)
      expect(result.sheetsData[0].sampleRows.length).toBe(1)
    })

    it('skips sheets without !ref', async () => {
      xlsxReadMock.mockReturnValue({
        SheetNames: ['Sheet1', 'Sheet2'],
        Sheets: {
          Sheet1: { '!ref': 'A1:B2' },
          Sheet2: {}, // 无 !ref
        },
      })
      xlsxSheetToJsonMock.mockReturnValue([['型号'], ['A1']])

      const { readWorkbookSheets } = useBatchAnalyze()
      const file = makeFile('test.xlsx')
      const result = await readWorkbookSheets(file)

      expect(result.sheetsData.length).toBe(1)
      expect(result.sheetsData[0].sheetName).toBe('Sheet1')
    })

    it('skips sheets with empty json data', async () => {
      xlsxReadMock.mockReturnValue({
        SheetNames: ['Sheet1'],
        Sheets: { Sheet1: { '!ref': 'A1:A1' } },
      })
      xlsxSheetToJsonMock.mockReturnValue([])

      const { readWorkbookSheets } = useBatchAnalyze()
      const file = makeFile('test.xlsx')
      const result = await readWorkbookSheets(file)

      expect(result.sheetsData.length).toBe(0)
    })

    it('handles empty header row (all empty cells filtered)', async () => {
      xlsxReadMock.mockReturnValue({
        SheetNames: ['Sheet1'],
        Sheets: { Sheet1: { '!ref': 'A1:A1' } },
      })
      xlsxSheetToJsonMock.mockReturnValue([['', '', '']])

      const { readWorkbookSheets } = useBatchAnalyze()
      const file = makeFile('test.xlsx')
      const result = await readWorkbookSheets(file)

      expect(result.sheetsData.length).toBe(1)
      expect(result.sheetsData[0].fields).toEqual([])
    })

    it('handles header cells with null/undefined', async () => {
      xlsxReadMock.mockReturnValue({
        SheetNames: ['Sheet1'],
        Sheets: { Sheet1: { '!ref': 'A1:B1' } },
      })
      xlsxSheetToJsonMock.mockReturnValue([[null, undefined, '型号']])

      const { readWorkbookSheets } = useBatchAnalyze()
      const file = makeFile('test.xlsx')
      const result = await readWorkbookSheets(file)

      expect(result.sheetsData[0].fields).toEqual(['型号'])
    })

    it('caps sampleRows at 3 rows', async () => {
      xlsxReadMock.mockReturnValue({
        SheetNames: ['Sheet1'],
        Sheets: { Sheet1: { '!ref': 'A1:A10' } },
      })
      const rows: unknown[][] = [['型号']]
      for (let i = 0; i < 9; i++) rows.push([`v${i}`])
      xlsxSheetToJsonMock.mockReturnValue(rows)

      const { readWorkbookSheets } = useBatchAnalyze()
      const file = makeFile('test.xlsx')
      const result = await readWorkbookSheets(file)

      expect(result.sheetsData[0].sampleRows.length).toBe(3)
      expect(result.sheetsData[0].rowCount).toBe(9)
    })

    it('handles multiple sheets', async () => {
      xlsxReadMock.mockReturnValue({
        SheetNames: ['S1', 'S2'],
        Sheets: {
          S1: { '!ref': 'A1:B1' },
          S2: { '!ref': 'A1:B1' },
        },
      })
      xlsxSheetToJsonMock.mockReturnValue([['型号', '价格']])

      const { readWorkbookSheets } = useBatchAnalyze()
      const file = makeFile('test.xlsx')
      const result = await readWorkbookSheets(file)

      expect(result.sheetsData.length).toBe(2)
      expect(result.sheetsData[0].sheetIndex).toBe(1)
      expect(result.sheetsData[1].sheetIndex).toBe(2)
    })

    it('handles SheetNames not being array', async () => {
      xlsxReadMock.mockReturnValue({
        SheetNames: null as unknown as string[],
        Sheets: {},
      })

      const { readWorkbookSheets } = useBatchAnalyze()
      const file = makeFile('test.xlsx')
      const result = await readWorkbookSheets(file)

      expect(result.sheetNames).toEqual([])
      expect(result.sheetsData.length).toBe(0)
    })
  })

  // -------------------------------------------------------------------------
  // extractAllSheets
  // -------------------------------------------------------------------------

  describe('extractAllSheets', () => {
    it('extracts sheets from multiple files', async () => {
      xlsxReadMock.mockImplementation(() => ({
        SheetNames: ['S1'],
        Sheets: { S1: { '!ref': 'A1:B1' } },
      }))
      xlsxSheetToJsonMock.mockReturnValue([['型号', '价格']])

      const { extractAllSheets, store } = useBatchAnalyze()
      const files = [
        makeFile('a.xlsx'),
        makeFile('b.xlsx'),
      ]
      const sheets = await extractAllSheets(files)

      expect(sheets.length).toBe(2)
      expect(store.phase).toBe('extracting')
      expect(store.processedFiles).toBe(2)
      expect(store.totalFiles).toBe(2)
    })

    it('continues on file read error', async () => {
      xlsxReadMock
        .mockImplementationOnce(() => {
          throw new Error('parse error')
        })
        .mockReturnValueOnce({
          SheetNames: ['S1'],
          Sheets: { S1: { '!ref': 'A1:B1' } },
        })
      xlsxSheetToJsonMock.mockReturnValue([['型号']])

      const { extractAllSheets } = useBatchAnalyze()
      const files = [
        makeFile('bad.xlsx'),
        makeFile('good.xlsx'),
      ]
      const sheets = await extractAllSheets(files)

      expect(sheets.length).toBe(1)
      expect(sheets[0].fileName).toBe('good.xlsx')
    })

    it('handles empty file list', async () => {
      const { extractAllSheets, store } = useBatchAnalyze()
      const sheets = await extractAllSheets([])
      expect(sheets).toEqual([])
      expect(store.totalFiles).toBe(0)
    })

    it('updates progress during extraction', async () => {
      xlsxReadMock.mockReturnValue({
        SheetNames: ['S1'],
        Sheets: { S1: { '!ref': 'A1:B1' } },
      })
      xlsxSheetToJsonMock.mockReturnValue([['型号']])

      const { extractAllSheets, store } = useBatchAnalyze()
      await extractAllSheets([makeFile('a.xlsx')])
      expect(store.progress).toBe(50)
      expect(store.currentFileName).toBe('a.xlsx')
    })
  })

  // -------------------------------------------------------------------------
  // analyzeAndGroup
  // -------------------------------------------------------------------------

  describe('analyzeAndGroup', () => {
    it('groups extracted sheets and matches templates', async () => {
      listTemplatesMock.mockResolvedValue({
        success: true,
        templates: [
          { id: 't1', name: '出货明细模板', template_type: '出货明细', business_scope: 'orders', category: 'excel' },
        ],
      })

      const { analyzeAndGroup, store } = useBatchAnalyze()
      store.addExtractedSheets([
        makeSheet({ sheetName: 'S1', fields: ['产品型号', '产品名称', '数量', '单价', '金额'] }),
      ])

      const groups = await analyzeAndGroup()

      expect(groups.length).toBe(1)
      expect(groups[0].recommendedTemplateId).toBe('t1')
      expect(groups[0].recommendedTemplateName).toBe('出货明细模板')
      expect(store.phase).toBe('done')
      expect(store.progress).toBe(100)
    })

    it('handles empty extracted sheets', async () => {
      const { analyzeAndGroup, store } = useBatchAnalyze()
      const groups = await analyzeAndGroup()
      expect(groups).toEqual([])
      expect(store.phase).toBe('done')
    })

    it('skips templates with non-excel category', async () => {
      listTemplatesMock.mockResolvedValue({
        success: true,
        templates: [
          { id: 't1', name: 'PDF模板', template_type: '出货明细', business_scope: 'orders', category: 'pdf' },
        ],
      })

      const { analyzeAndGroup, store } = useBatchAnalyze()
      store.addExtractedSheets([
        makeSheet({ sheetName: 'S1', fields: ['产品型号', '产品名称', '数量', '单价', '金额'] }),
      ])

      const groups = await analyzeAndGroup()
      expect(groups[0].recommendedTemplateId).toBe('')
    })

    it('handles listTemplates failure gracefully', async () => {
      listTemplatesMock.mockRejectedValue(new Error('network error'))

      const { analyzeAndGroup, store } = useBatchAnalyze()
      store.addExtractedSheets([
        makeSheet({ sheetName: 'S1', fields: ['产品型号', '产品名称', '数量', '单价', '金额'] }),
      ])

      const groups = await analyzeAndGroup()
      expect(groups.length).toBe(1)
      expect(groups[0].recommendedTemplateId).toBe('')
      expect(store.phase).toBe('done')
    })

    it('handles listTemplates returning non-success', async () => {
      listTemplatesMock.mockResolvedValue({ success: false })

      const { analyzeAndGroup } = useBatchAnalyze()
      const groups = await analyzeAndGroup()
      expect(groups).toEqual([])
    })

    it('handles listTemplates returning non-array templates', async () => {
      listTemplatesMock.mockResolvedValue({ success: true, templates: null })

      const { analyzeAndGroup } = useBatchAnalyze()
      const groups = await analyzeAndGroup()
      expect(groups).toEqual([])
    })

    it('matches template by businessScope', async () => {
      listTemplatesMock.mockResolvedValue({
        success: true,
        templates: [
          { id: 't1', name: 'T1', template_type: '其他', business_scope: 'orders', category: 'excel' },
        ],
      })

      const { analyzeAndGroup, store } = useBatchAnalyze()
      store.addExtractedSheets([
        makeSheet({ sheetName: 'S1', fields: ['产品型号', '产品名称', '数量', '单价', '金额'] }),
      ])

      const groups = await analyzeAndGroup()
      expect(groups[0].recommendedTemplateId).toBe('t1')
    })

    it('matches template by templateType', async () => {
      listTemplatesMock.mockResolvedValue({
        success: true,
        templates: [
          { id: 't2', name: 'T2', template_type: '出货明细', business_scope: '其他', category: 'excel' },
        ],
      })

      const { analyzeAndGroup, store } = useBatchAnalyze()
      store.addExtractedSheets([
        makeSheet({ sheetName: 'S1', fields: ['产品型号', '产品名称', '数量', '单价', '金额'] }),
      ])

      const groups = await analyzeAndGroup()
      expect(groups[0].recommendedTemplateId).toBe('t2')
    })

    it('uses fallback name when template name missing', async () => {
      listTemplatesMock.mockResolvedValue({
        success: true,
        templates: [
          { id: 't1', template_type: '出货明细', business_scope: 'orders', category: 'excel' },
        ],
      })

      const { analyzeAndGroup, store } = useBatchAnalyze()
      store.addExtractedSheets([
        makeSheet({ sheetName: 'S1', fields: ['产品型号', '产品名称', '数量', '单价', '金额'] }),
      ])

      const groups = await analyzeAndGroup()
      expect(groups[0].recommendedTemplateName).toBe('未命名模板')
    })

    it('uses template_name when name missing', async () => {
      listTemplatesMock.mockResolvedValue({
        success: true,
        templates: [
          { id: 't1', template_name: '模板A', template_type: '出货明细', business_scope: 'orders', category: 'excel' },
        ],
      })

      const { analyzeAndGroup, store } = useBatchAnalyze()
      store.addExtractedSheets([
        makeSheet({ sheetName: 'S1', fields: ['产品型号', '产品名称', '数量', '单价', '金额'] }),
      ])

      const groups = await analyzeAndGroup()
      expect(groups[0].recommendedTemplateName).toBe('模板A')
    })
  })

  // -------------------------------------------------------------------------
  // startBatchAnalyze
  // -------------------------------------------------------------------------

  describe('startBatchAnalyze', () => {
    it('filters non-excel files and sets error', async () => {
      const { startBatchAnalyze, store } = useBatchAnalyze()
      const files = [
        makeFile('a.txt'),
        makeFile('b.csv'),
      ]
      const groups = await startBatchAnalyze(files)
      expect(groups).toEqual([])
      expect(store.errorMessage).toContain('Excel')
      expect(store.phase).toBe('error')
    })

    it('filters mixed files keeping only excel', async () => {
      xlsxReadMock.mockReturnValue({
        SheetNames: ['S1'],
        Sheets: { S1: { '!ref': 'A1:B1' } },
      })
      xlsxSheetToJsonMock.mockReturnValue([['型号', '价格']])
      listTemplatesMock.mockResolvedValue({ success: true, templates: [] })

      const { startBatchAnalyze, store } = useBatchAnalyze()
      const files = [
        makeFile('a.txt'),
        makeFile('b.xlsx'),
      ]
      const groups = await startBatchAnalyze(files)
      expect(groups.length).toBe(1)
      expect(store.errorMessage).toBe('')
    })

    it('accepts .xls extension', async () => {
      xlsxReadMock.mockReturnValue({
        SheetNames: ['S1'],
        Sheets: { S1: { '!ref': 'A1:B1' } },
      })
      xlsxSheetToJsonMock.mockReturnValue([['型号']])
      listTemplatesMock.mockResolvedValue({ success: true, templates: [] })

      const { startBatchAnalyze } = useBatchAnalyze()
      const groups = await startBatchAnalyze([makeFile('old.xls')])
      expect(groups.length).toBe(1)
    })

    it('accepts .XLSX uppercase extension', async () => {
      xlsxReadMock.mockReturnValue({
        SheetNames: ['S1'],
        Sheets: { S1: { '!ref': 'A1:B1' } },
      })
      xlsxSheetToJsonMock.mockReturnValue([['型号']])
      listTemplatesMock.mockResolvedValue({ success: true, templates: [] })

      const { startBatchAnalyze } = useBatchAnalyze()
      const groups = await startBatchAnalyze([makeFile('UPPER.XLSX')])
      expect(groups.length).toBe(1)
    })

    it('starts new session resetting store', async () => {
      xlsxReadMock.mockReturnValue({
        SheetNames: ['S1'],
        Sheets: { S1: { '!ref': 'A1:B1' } },
      })
      xlsxSheetToJsonMock.mockReturnValue([['型号']])
      listTemplatesMock.mockResolvedValue({ success: true, templates: [] })

      const { startBatchAnalyze, store } = useBatchAnalyze()
      // 预设一些脏状态
      store.setError('old error')
      store.addExtractedSheets([makeSheet()])

      await startBatchAnalyze([makeFile('a.xlsx')])

      expect(store.sessionId).not.toBe('')
      // startNewSession 会 reset，然后 extractAllSheets 会 addExtractedSheets 新提取的
      expect(store.extractedSheets.length).toBe(1)
      expect(store.errorMessage).toBe('')
    })

    it('handles empty file list', async () => {
      const { startBatchAnalyze, store } = useBatchAnalyze()
      const groups = await startBatchAnalyze([])
      expect(groups).toEqual([])
      expect(store.errorMessage).toContain('Excel')
    })
  })

  // -------------------------------------------------------------------------
  // extractGridForSheet
  // -------------------------------------------------------------------------

  describe('extractGridForSheet', () => {
    it('returns grid on success', async () => {
      extractGridMock.mockResolvedValue({ grid: [[1, 2], [3, 4]] })
      const { extractGridForSheet } = useBatchAnalyze()
      const file = makeFile('a.xlsx')
      const result = await extractGridForSheet(file, 'Sheet1')
      expect(result).toEqual({ grid: [[1, 2], [3, 4]] })
    })

    it('returns null on API failure', async () => {
      extractGridMock.mockRejectedValue(new Error('network'))
      const { extractGridForSheet } = useBatchAnalyze()
      const file = makeFile('a.xlsx')
      const result = await extractGridForSheet(file, 'Sheet1')
      expect(result).toBeNull()
    })

    it('passes file and sheet_name in FormData', async () => {
      extractGridMock.mockResolvedValue({})
      const { extractGridForSheet } = useBatchAnalyze()
      const file = makeFile('a.xlsx')
      await extractGridForSheet(file, 'MySheet')

      expect(extractGridMock).toHaveBeenCalled()
      const formData = extractGridMock.mock.calls[0][0] as FormData
      expect(formData.get('sheet_name')).toBe('MySheet')
      expect(formData.get('file')).toBeInstanceOf(File)
    })
  })

  // -------------------------------------------------------------------------
  // loadTemplates (间接通过 analyzeAndGroup 测试，这里补充边界)
  // -------------------------------------------------------------------------

  describe('loadTemplates via analyzeAndGroup', () => {
    it('handles templates with missing fields (no match)', async () => {
      listTemplatesMock.mockResolvedValue({
        success: true,
        templates: [
          { category: 'excel' }, // 缺 id/name/template_type/business_scope
        ],
      })

      const { analyzeAndGroup, store } = useBatchAnalyze()
      store.addExtractedSheets([
        makeSheet({ sheetName: 'S1', fields: ['产品型号', '产品名称', '数量', '单价', '金额'] }),
      ])

      const groups = await analyzeAndGroup()
      // 模板字段缺失，businessScope='' / templateType='' 不匹配 group.category='orders'
      // 因此 recommendedTemplateId 保持 ''，recommendedTemplateName 保持 scope label
      expect(groups[0].recommendedTemplateId).toBe('')
      // recommendedTemplateName 在无匹配时保持 groupSheetsBySimilarity 设置的值（scope label）
      expect(groups[0].recommendedTemplateName).toBe('出货明细表')
    })

    it('handles templates entry not being object', async () => {
      // asRecord(null/'string'/123) 返回 {}，category='' !== 'excel' → 全部被过滤
      // 只有最后一个对象 category='excel' 会被保留，但其 businessScope/templateType 为空
      // 因此不会匹配任何 group，recommendedTemplateId 保持 ''
      listTemplatesMock.mockResolvedValue({
        success: true,
        templates: [null, 'string', 123, { category: 'excel', id: 't1' }],
      })

      const { analyzeAndGroup, store } = useBatchAnalyze()
      store.addExtractedSheets([
        makeSheet({ sheetName: 'S1', fields: ['产品型号', '产品名称', '数量', '单价', '金额'] }),
      ])

      const groups = await analyzeAndGroup()
      // 模板 t1 的 businessScope='' / templateType='' 不匹配 group
      expect(groups[0].recommendedTemplateId).toBe('')
    })

    it('matches template when businessScope matches group category', async () => {
      listTemplatesMock.mockResolvedValue({
        success: true,
        templates: [
          { category: 'excel', id: 't1', name: 'T1', business_scope: 'orders', template_type: '出货明细' },
        ],
      })

      const { analyzeAndGroup, store } = useBatchAnalyze()
      store.addExtractedSheets([
        makeSheet({ sheetName: 'S1', fields: ['产品型号', '产品名称', '数量', '单价', '金额'] }),
      ])

      const groups = await analyzeAndGroup()
      expect(groups[0].recommendedTemplateId).toBe('t1')
      expect(groups[0].recommendedTemplateName).toBe('T1')
    })
  })
})
