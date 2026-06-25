import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ExcelPreview from '@/components/template/ExcelPreview.vue'

function mountExcel(propsOverrides = {}) {
  return mount(ExcelPreview, {
    props: {
      fields: [],
      sampleRows: [],
      rows: 6,
      columns: 5,
      title: 'Excel 模板预览',
      gridData: null,
      ...propsOverrides,
    },
  })
}

describe('ExcelPreview', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders excel-preview container', () => {
    const wrapper = mountExcel()
    expect(wrapper.find('.excel-preview').exists()).toBe(true)
  })

  it('renders fake-excel container', () => {
    const wrapper = mountExcel()
    expect(wrapper.find('.fake-excel').exists()).toBe(true)
  })

  it('renders title in toolbar', () => {
    const wrapper = mountExcel({ title: '自定义标题' })
    expect(wrapper.find('.excel-title').text()).toBe('自定义标题')
  })

  it('uses default title', () => {
    const wrapper = mountExcel()
    expect(wrapper.find('.excel-title').text()).toBe('Excel 模板预览')
  })

  it('hasGridData returns false when gridData is null', () => {
    const wrapper = mountExcel({ gridData: null })
    expect(wrapper.vm.hasGridData).toBe(false)
  })

  it('hasGridData returns false when gridData has empty rows', () => {
    const wrapper = mountExcel({ gridData: { rows: [] } })
    expect(wrapper.vm.hasGridData).toBe(false)
  })

  it('hasGridData returns true when gridData has rows', () => {
    const wrapper = mountExcel({
      gridData: { rows: [[{ text: 'A', col: 0 }]] },
    })
    expect(wrapper.vm.hasGridData).toBe(true)
  })

  it('hasGridData returns false when gridData.rows is not an array', () => {
    const wrapper = mountExcel({ gridData: { rows: 'not array' } })
    expect(wrapper.vm.hasGridData).toBe(false)
  })

  it('gridRows returns empty when no gridData', () => {
    const wrapper = mountExcel()
    expect(wrapper.vm.gridRows).toEqual([])
  })

  it('gridRows returns rows from gridData', () => {
    const rows = [[{ text: 'A', col: 0 }], [{ text: 'B', col: 0 }]]
    const wrapper = mountExcel({ gridData: { rows } })
    expect(wrapper.vm.gridRows).toEqual(rows)
  })

  it('renders grid table when hasGridData is true', () => {
    const wrapper = mountExcel({
      gridData: { rows: [[{ text: 'A', col: 0 }, { text: 'B', col: 1 }]] },
    })
    expect(wrapper.find('.real-grid-table').exists()).toBe(true)
    expect(wrapper.findAll('.real-grid-cell')).toHaveLength(2)
  })

  it('renders row numbers in grid table', () => {
    const wrapper = mountExcel({
      gridData: {
        rows: [
          [{ text: 'A', col: 0 }],
          [{ text: 'B', col: 0 }],
        ],
      },
    })
    const rowNums = wrapper.findAll('.real-row-num')
    expect(rowNums).toHaveLength(2)
    expect(rowNums[0].text()).toBe('1')
    expect(rowNums[1].text()).toBe('2')
  })

  it('applies has-content class to cells with text', () => {
    const wrapper = mountExcel({
      gridData: {
        rows: [[{ text: 'A', col: 0 }, { text: '', col: 1 }]],
      },
    })
    const cells = wrapper.findAll('.real-grid-cell')
    expect(cells[0].classes()).toContain('has-content')
    expect(cells[1].classes()).not.toContain('has-content')
  })

  it('applies is-merged class to cells with rowspan/colspan', () => {
    const wrapper = mountExcel({
      gridData: {
        rows: [
          [
            { text: 'A', col: 0, rowspan: 2 },
            { text: 'B', col: 1, colspan: 2 },
          ],
        ],
      },
    })
    const cells = wrapper.findAll('.real-grid-cell')
    expect(cells[0].classes()).toContain('is-merged')
    expect(cells[1].classes()).toContain('is-merged')
  })

  it('displayRows returns default rows when no sampleRows', () => {
    const wrapper = mountExcel({ rows: 8 })
    expect(wrapper.vm.displayRows).toBe(8)
  })

  it('displayRows returns max of rows and sampleRows length', () => {
    const wrapper = mountExcel({
      rows: 3,
      sampleRows: [{ a: 1 }, { b: 2 }, { c: 3 }, { d: 4 }, { e: 5 }],
    })
    expect(wrapper.vm.displayRows).toBe(5)
  })

  it('displayColumns returns default columns when no fields', () => {
    const wrapper = mountExcel({ columns: 7 })
    expect(wrapper.vm.displayColumns).toBe(7)
  })

  it('displayColumns returns max of columns and fields length', () => {
    const wrapper = mountExcel({
      columns: 3,
      fields: [{ label: 'A' }, { label: 'B' }, { label: 'C' }, { label: 'D' }],
    })
    expect(wrapper.vm.displayColumns).toBe(4)
  })

  it('columnHeaders returns labels from fields', () => {
    const wrapper = mountExcel({
      fields: [{ label: '名称' }, { label: '价格' }],
    })
    expect(wrapper.vm.columnHeaders).toEqual(['名称', '价格'])
  })

  it('columnHeaders uses name when label is missing', () => {
    const wrapper = mountExcel({
      fields: [{ name: '字段1' }, { label: '字段2' }],
    })
    expect(wrapper.vm.columnHeaders).toEqual(['字段1', '字段2'])
  })

  it('columnHeaders returns empty when no fields', () => {
    const wrapper = mountExcel()
    expect(wrapper.vm.columnHeaders).toEqual([])
  })

  it('getColumnHeader returns field label when available', () => {
    const wrapper = mountExcel({
      fields: [{ label: '品名' }, { label: '价格' }],
    })
    expect(wrapper.vm.getColumnHeader(0)).toBe('品名')
    expect(wrapper.vm.getColumnHeader(1)).toBe('价格')
  })

  it('getColumnHeader returns letter when no field at index', () => {
    const wrapper = mountExcel()
    expect(wrapper.vm.getColumnHeader(0)).toBe('A')
    expect(wrapper.vm.getColumnHeader(1)).toBe('B')
    expect(wrapper.vm.getColumnHeader(9)).toBe('J')
  })

  it('getColumnHeader returns empty string for index beyond letters', () => {
    const wrapper = mountExcel()
    expect(wrapper.vm.getColumnHeader(10)).toBe('')
  })

  it('getCellContent returns sample row value by header key', () => {
    const wrapper = mountExcel({
      fields: [{ label: '品名' }, { label: '价格' }],
      sampleRows: [{ 品名: '鞋', 价格: 100 }],
    })
    expect(wrapper.vm.getCellContent(0, 0)).toBe('鞋')
    expect(wrapper.vm.getCellContent(0, 1)).toBe(100)
  })

  it('getCellContent returns sample row value by index when no headers', () => {
    const wrapper = mountExcel({
      sampleRows: [{ a: 'X', b: 'Y' }],
    })
    expect(wrapper.vm.getCellContent(0, 0)).toBe('X')
    expect(wrapper.vm.getCellContent(0, 1)).toBe('Y')
  })

  it('getCellContent returns empty for undefined sample row value', () => {
    const wrapper = mountExcel({
      fields: [{ label: '品名' }],
      sampleRows: [{ 品名: '鞋' }],
    })
    expect(wrapper.vm.getCellContent(0, 1)).toBe('')
  })

  it('getCellContent returns header on first row when no sampleRows', () => {
    const wrapper = mountExcel({
      fields: [{ label: '品名' }, { label: '价格' }],
    })
    expect(wrapper.vm.getCellContent(0, 0)).toBe('品名')
    expect(wrapper.vm.getCellContent(0, 1)).toBe('价格')
  })

  it('getCellContent returns field value/sample on rows after first', () => {
    const wrapper = mountExcel({
      fields: [
        { label: '品名', value: '鞋' },
        { label: '价格', sample: '¥99' },
      ],
    })
    expect(wrapper.vm.getCellContent(1, 0)).toBe('鞋')
    expect(wrapper.vm.getCellContent(1, 1)).toBe('¥99')
  })

  it('getCellContent returns empty for out-of-range rows', () => {
    const wrapper = mountExcel({
      fields: [{ label: '品名' }],
    })
    expect(wrapper.vm.getCellContent(5, 0)).toBe('')
  })

  it('renders excel-headers section when no gridData', () => {
    const wrapper = mountExcel()
    expect(wrapper.find('.excel-headers').exists()).toBe(true)
  })

  it('renders excel-body section when no gridData', () => {
    const wrapper = mountExcel()
    expect(wrapper.find('.excel-body').exists()).toBe(true)
  })

  it('renders correct number of column headers', () => {
    const wrapper = mountExcel({
      fields: [{ label: 'A' }, { label: 'B' }, { label: 'C' }],
      columns: 2,
    })
    // displayColumns = max(2, 3) = 3
    expect(wrapper.findAll('.col-header')).toHaveLength(3)
  })

  it('renders correct number of rows', () => {
    const wrapper = mountExcel({ rows: 4 })
    expect(wrapper.findAll('.excel-row')).toHaveLength(4)
  })

  it('renders row numbers in body', () => {
    const wrapper = mountExcel({ rows: 3 })
    const rowNums = wrapper.findAll('.row-num')
    expect(rowNums[0].text()).toBe('1')
    expect(rowNums[1].text()).toBe('2')
    expect(rowNums[2].text()).toBe('3')
  })

  it('applies has-content class to cells with content in body', () => {
    const wrapper = mountExcel({
      fields: [{ label: '品名' }],
      sampleRows: [{ 品名: '鞋' }],
    })
    const cells = wrapper.findAll('.excel-cell')
    // First row, first column should have content
    expect(cells[0].classes()).toContain('has-content')
  })

  it('renders cell text in body', () => {
    const wrapper = mountExcel({
      fields: [{ label: '品名' }],
      sampleRows: [{ 品名: '运动鞋' }],
    })
    expect(wrapper.find('.cell-text').text()).toBe('运动鞋')
  })
})
