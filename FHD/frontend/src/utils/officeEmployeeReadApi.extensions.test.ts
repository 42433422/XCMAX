import { describe, expect, it } from 'vitest'
import {
  isOfficeDockingFileSupported,
  resolveOfficeReadEmployeeForFile,
} from './officeEmployeeReadApi'

describe('office employee file extension contract', () => {
  it('matches the packaged readers and rejects unsupported legacy Excel/PPT formats', () => {
    for (const fileName of [
      'book.xlsx',
      'book.xlsm',
      'document.docx',
      'report.pdf',
      'slides.pptx',
    ]) {
      expect(isOfficeDockingFileSupported(fileName)).toBe(true)
      expect(resolveOfficeReadEmployeeForFile(fileName)).not.toBe('')
    }

    for (const fileName of ['legacy.xls', 'legacy.ppt', 'legacy.doc', 'data.csv']) {
      expect(isOfficeDockingFileSupported(fileName)).toBe(false)
      expect(resolveOfficeReadEmployeeForFile(fileName)).toBe('')
    }
  })
})
