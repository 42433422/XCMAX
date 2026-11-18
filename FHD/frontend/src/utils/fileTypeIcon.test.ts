import { describe, expect, it } from 'vitest'
import { fileIconName } from './fileTypeIcon'

describe('fileIconName', () => {
  it('按扩展名映射到 VS Code 文件图标', () => {
    expect(fileIconName('邻居贾总.xlsx')).toBe('vscode-icons:file-type-excel')
    expect(fileIconName('合同.docx')).toBe('vscode-icons:file-type-word')
    expect(fileIconName('账单.pdf')).toBe('vscode-icons:file-type-pdf')
    expect(fileIconName('照片.png')).toBe('vscode-icons:file-type-image')
    expect(fileIconName('归档.zip')).toBe('vscode-icons:file-type-zip')
  })

  it('没有文件名时按业务分类回退', () => {
    expect(fileIconName('', 'excel')).toBe('vscode-icons:file-type-excel')
    expect(fileIconName('', 'pdf')).toBe('vscode-icons:file-type-pdf')
    expect(fileIconName('', 'image')).toBe('vscode-icons:file-type-image')
  })

  it('未知类型使用通用文件图标', () => {
    expect(fileIconName('数据.unknown')).toBe('vscode-icons:default-file')
    expect(fileIconName('')).toBe('vscode-icons:default-file')
  })
})
