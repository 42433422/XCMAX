import { describe, expect, it } from 'vitest'

import { formatEtlBytes, selectEtlSourceFiles } from './etlFileSelection'

function folderFile(contents: string, name: string, relativePath: string) {
  const file = new File([contents], name, { lastModified: 123 })
  Object.defineProperty(file, 'webkitRelativePath', { value: relativePath })
  return file
}

describe('selectEtlSourceFiles', () => {
  it('keeps supported files and their folder-relative paths', () => {
    const selection = selectEtlSourceFiles([
      folderFile('a', 'customers.csv', '华东数据/客户/customers.csv'),
      folderFile('b', 'products.xlsx', '华东数据/产品/products.xlsx'),
    ], 1024)

    expect(selection.folderName).toBe('华东数据')
    expect(selection.accepted.map((item) => item.relativePath)).toEqual([
      '华东数据/客户/customers.csv',
      '华东数据/产品/products.xlsx',
    ])
    expect(selection.ignored).toEqual([])
  })

  it('ignores unsupported, oversized, and duplicate files with stable reasons', () => {
    const first = folderFile('1234', 'data.csv', '批次/data.csv')
    const selection = selectEtlSourceFiles([
      first,
      first,
      folderFile('1234', 'notes.txt', '批次/notes.txt'),
      folderFile('123456', 'large.csv', '批次/large.csv'),
    ], 4)

    expect(selection.accepted).toHaveLength(1)
    expect(selection.ignored.map((item) => item.reason)).toEqual([
      'duplicate',
      'unsupported',
      'too_large',
    ])
  })

  it('removes traversal segments from display-only relative paths', () => {
    const selection = selectEtlSourceFiles([
      folderFile('a', 'data.csv', '../unsafe/./data.csv'),
    ], 1024)

    expect(selection.accepted[0]?.relativePath).toBe('unsafe/data.csv')
  })
})

describe('formatEtlBytes', () => {
  it('formats folder totals for the upload summary', () => {
    expect(formatEtlBytes(12)).toBe('12 B')
    expect(formatEtlBytes(1536)).toBe('1.5 KB')
    expect(formatEtlBytes(2 * 1024 * 1024)).toBe('2.0 MB')
  })
})
