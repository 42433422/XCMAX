import { describe, expect, it } from 'vitest'
import {
  BATCH_MAX_FILES,
  buildIntakeReport,
  intakeItemsFor,
  mergeIntakeReports,
  preflightDocuments,
} from './documentIntake'

function fakeFile(name: string, size = 1024): File {
  return { name, size } as File
}

describe('preflightDocuments', () => {
  it('归档临时文件与不支持的格式并给出原因', () => {
    const report = preflightDocuments(
      [fakeFile('26年销售明细.xlsx'), fakeFile('~$七彩乐园.xlsx'), fakeFile('大桶商标.btw'), fakeFile('driver.exe')],
      'template',
    )
    expect(report.accepted.map((file) => file.name)).toEqual(['26年销售明细.xlsx'])
    expect(report.skipped.map((item) => item.reason)).toEqual(['temp_file', 'unsupported', 'unsupported'])
    expect(report.summary).toContain('可导入 1 个')
    expect(report.summary).toContain('跳过 3 个')
  })

  it('旧 XLS 标记为需转换但保留在处理队列中', () => {
    const report = preflightDocuments([fakeFile('大桶商标.xls'), fakeFile('26年生产单.xlsx')], 'template')
    expect(report.convertible.map((file) => file.name)).toEqual(['大桶商标.xls'])
    expect(report.accepted.map((file) => file.name)).toEqual(['大桶商标.xls', '26年生产单.xlsx'])
    expect(report.summary).toContain('需转换 1 个')
    expect(report.blocked).toBe(false)
  })

  it('同名同大小的重复文件只保留一份', () => {
    const report = preflightDocuments(
      [fakeFile('宗南.xlsx', 2048), fakeFile('宗南.xlsx', 2048), fakeFile('宗南.xlsx', 4096)],
      'template',
    )
    expect(report.accepted).toHaveLength(2)
    expect(report.skipped).toHaveLength(1)
    expect(report.skipped[0].reason).toBe('duplicate')
  })

  it('超过单批数量上限的文件被跳过', () => {
    const files = Array.from({ length: BATCH_MAX_FILES + 2 }, (_, index) => fakeFile(`表${index}.xlsx`, 10 + index))
    const report = preflightDocuments(files, 'analysis')
    expect(report.accepted).toHaveLength(BATCH_MAX_FILES)
    expect(report.skipped.every((item) => item.reason === 'batch_limit')).toBe(true)
  })

  it('附件通道只接受图片、PDF 与文本', () => {
    const report = preflightDocuments(
      [fakeFile('公司章程.pdf'), fakeFile('截图.png'), fakeFile('销售明细.xlsx'), fakeFile('大文件.pdf', 13 * 1024 * 1024)],
      'context',
    )
    expect(report.accepted.map((file) => file.name)).toEqual(['公司章程.pdf', '截图.png'])
    expect(report.skipped.map((item) => item.reason)).toEqual(['unsupported', 'too_large'])
  })

  it('全部不可导入时标记 blocked', () => {
    const report = preflightDocuments([fakeFile('商标.btw'), fakeFile('~$临时.xlsx')], 'template')
    expect(report.blocked).toBe(true)
    expect(report.summary).toContain('可导入 0 个')
  })
})

describe('mergeIntakeReports', () => {
  it('追加一批后合并展示统计', () => {
    const first = preflightDocuments([fakeFile('甲.xlsx')], 'template')
    const second = preflightDocuments([fakeFile('乙.xlsx'), fakeFile('丙.btw')], 'template')
    const merged = mergeIntakeReports(first, second)
    expect(merged.accepted.map((file) => file.name)).toEqual(['甲.xlsx', '乙.xlsx'])
    expect(merged.skipped).toHaveLength(1)
    expect(merged.total).toBe(3)
  })

  it('报告聚合不改变已有判定', () => {
    const items = intakeItemsFor([fakeFile('甲.xlsx'), fakeFile('~$乙.xlsx')], 'template')
    const report = buildIntakeReport(items, 'template')
    expect(report.items.map((item) => item.verdict)).toEqual(['accepted', 'skipped'])
  })
})
