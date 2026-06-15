import { describe, it, expect } from 'vitest'
import {
  stripSampleRowsKeepTemplateShape,
  stripGridPreviewData,
} from './templatePreviewSanitize'

describe('templatePreviewSanitize', () => {
  describe('stripSampleRowsKeepTemplateShape', () => {
    it('returns empty array when no sample rows and no fallback fields', () => {
      expect(stripSampleRowsKeepTemplateShape([], [])).toEqual([])
    })

    it('returns shape from fallback fields when no sample rows', () => {
      const result = stripSampleRowsKeepTemplateShape([], [
        { label: 'Name' },
        { label: 'Age' },
      ])
      expect(result).toEqual([{ Name: '', Age: '' }])
    })

    it('returns shape from first row keys', () => {
      const result = stripSampleRowsKeepTemplateShape(
        [{ Name: 'Alice', Age: 30 }],
        [],
      )
      expect(result).toEqual([{ Name: '', Age: '' }])
    })

    it('returns empty array when first row has no keys', () => {
      const result = stripSampleRowsKeepTemplateShape([{}], [])
      expect(result).toEqual([])
    })

    it('ignores non-array sample rows', () => {
      const result = stripSampleRowsKeepTemplateShape(null as any, [])
      expect(result).toEqual([])
    })

    it('filters empty labels from fallback fields', () => {
      const result = stripSampleRowsKeepTemplateShape([], [
        { label: 'Name' },
        { label: '' },
        { label: '  ' },
      ])
      expect(result).toEqual([{ Name: '' }])
    })
  })

  describe('stripGridPreviewData', () => {
    it('returns null for null input', () => {
      expect(stripGridPreviewData(null, [])).toBeNull()
    })

    it('returns null for non-object input', () => {
      expect(stripGridPreviewData('string', [])).toBeNull()
    })

    it('returns grid without rows array as-is', () => {
      const grid = { cols: 5 }
      expect(stripGridPreviewData(grid, [])).toEqual({ cols: 5 })
    })

    it('strips dynamic values from grid cells', () => {
      const grid = {
        rows: [
          [{ text: 'Header' }, { text: 'Value' }],
          [{ text: 'SubHeader' }, { text: 'SubValue' }],
          [{ text: '123' }, { text: '456.78' }],
        ],
      }
      const sampleRows = [{ col1: 'Value' }]
      const result = stripGridPreviewData(grid, sampleRows)
      // 'Value' is in sampleValueSet so it should be stripped (row 0)
      expect(result.rows[0][0].text).toBe('Header')
      expect(result.rows[0][1].text).toBe('')
      // Numeric values in row index > 1 should be stripped
      expect(result.rows[2][0].text).toBe('')
      expect(result.rows[2][1].text).toBe('')
    })

    it('preserves header-like text in first rows', () => {
      const grid = {
        rows: [
          [{ text: 'Name' }, { text: 'Amount' }],
        ],
      }
      const result = stripGridPreviewData(grid, [])
      expect(result.rows[0][0].text).toBe('Name')
      expect(result.rows[0][1].text).toBe('Amount')
    })

    it('handles non-array rows gracefully', () => {
      const grid = {
        rows: [null, 'string', 123],
      }
      const result = stripGridPreviewData(grid, [])
      expect(result.rows).toHaveLength(3)
    })

    it('handles cell objects with text property', () => {
      const grid = {
        rows: [
          [{ text: 'Date' }, { text: '2024-01-15' }],
        ],
      }
      const result = stripGridPreviewData(grid, [])
      // Date-like pattern in row index 0 should not be stripped
      expect(result.rows[0][0].text).toBe('Date')
    })

    it('strips date-like values in later rows', () => {
      const grid = {
        rows: [
          [{ text: 'Date' }],
          [{ text: 'SubHeader' }],
          [{ text: '2024-01-15' }],
        ],
      }
      const result = stripGridPreviewData(grid, [])
      expect(result.rows[2][0].text).toBe('')
    })

    it('strips long numeric strings', () => {
      const grid = {
        rows: [
          [{ text: 'ID' }],
          [{ text: 'SubHeader' }],
          [{ text: '123456' }],
        ],
      }
      const result = stripGridPreviewData(grid, [])
      expect(result.rows[2][0].text).toBe('')
    })

    it('handles plain string cells', () => {
      const grid = {
        rows: [
          ['Header'],
          ['SubHeader'],
          ['123.45'],
        ],
      }
      const result = stripGridPreviewData(grid, [])
      expect(result.rows[0][0]).toBe('Header')
      expect(result.rows[2][0]).toBe('')
    })
  })
})
