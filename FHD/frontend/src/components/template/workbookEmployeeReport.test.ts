import { describe, expect, it } from 'vitest'
import { workbookEmployeeReports } from './workbookEmployeeReport'

const entities = { customers: 0, purchase_units: 1, products: 2, records: 2 }

describe('workbook employee reports', () => {
  it('states imported entities, including zero, and a knowledge slice', () => {
    const [database, knowledge] = workbookEmployeeReports({
      detection: { degraded: false },
      knowledge: { action: 'new', documents: 1, degraded: false, lane: 'knowledge', content: '演示客户乙 购买螺母 5 桶，弹垫 2 桶' },
      business: { status: 'preview_ready', details: { entities } },
    })
    expect(database.outcome).toBe('预演预计：客户 0，购买单位 1，产品 2，明细 2。')
    expect(database.lines).toEqual(['客户 0', '购买单位 1', '产品 2', '明细 2'])
    expect(knowledge.outcome).toBe('预计整理 1 份文档。')
    expect(knowledge.lines[0]).toBe('文档 1 份')
    expect(knowledge.lines[1]).toContain('演示客户乙')
  })

  it('states zero documents without inventing a slice', () => {
    const [knowledge] = workbookEmployeeReports({
      knowledge: { action: 'new', documents: 0, degraded: false, lane: 'knowledge', content: '' },
    })
    expect(knowledge.outcome).toBe('预计整理 0 份文档。')
    expect(knowledge.lines).toEqual(['文档 0 份'])
  })

  it('does not claim success or present a column title when a line is degraded or skipped', () => {
    const reports = workbookEmployeeReports({
      detection: { degraded: true },
      knowledge: { action: 'error', documents: 0, degraded: true, lane: 'knowledge', content: '产品名称' },
      business: { status: 'preview_ready', details: { entities: { customers: 1, purchase_units: 1, products: 1, records: 1 } } },
    })
    expect(reports.map(item => item.outcome)).toEqual(['数据库导入员没有做完。', '知识整理员没有做完。'])
    expect(reports.flatMap(item => [item.outcome, ...item.lines]).join('\n')).not.toMatch(/本次入库|本次整理|已写入|成功|产品名称/)
  })

  it('prefers the save receipt counts over the preview tally', () => {
    const [database] = workbookEmployeeReports({
      business: {
        status: 'completed',
        details: { entities: { customers: 9, purchase_units: 9, products: 9, records: 9 } },
        receipt: { entities: { customers: 1, purchase_units: 1, products: 2, records: 3 } },
      },
    })
    expect(database.outcome).toBe('本次入库：客户 1，购买单位 1，产品 2，明细 3。')
  })
})
