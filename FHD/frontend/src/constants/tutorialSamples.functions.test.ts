import { describe, it, expect, beforeEach } from 'vitest'
import {
  TUTORIAL_DEPT_EMPLOYEE_SAMPLE_XLSX,
  TUTORIAL_QUICKSTART_EXCEL_A,
  TUTORIAL_QUICKSTART_EXCEL_B,
  TUTORIAL_QUICKSTART_WORD,
  TUTORIAL_SAMPLE_NAME_PREFIX,
  trackTutorialOfficeUploadPath,
  readTutorialOfficeUploadPaths,
  clearTutorialOfficeUploadPaths,
} from './tutorialSamples'

describe('tutorialSamples constants and functions', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  describe('TUTORIAL_DEPT_EMPLOYEE_SAMPLE_XLSX', () => {
    it('is a non-empty string path', () => {
      expect(TUTORIAL_DEPT_EMPLOYEE_SAMPLE_XLSX).toContain('/tutorial/')
      expect(TUTORIAL_DEPT_EMPLOYEE_SAMPLE_XLSX).toMatch(/\.xlsx$/)
    })
  })

  describe('TUTORIAL_QUICKSTART_EXCEL_A', () => {
    it('is a non-empty string path', () => {
      expect(TUTORIAL_QUICKSTART_EXCEL_A).toContain('/tutorial/')
    })
  })

  describe('TUTORIAL_QUICKSTART_EXCEL_B', () => {
    it('is a non-empty string path', () => {
      expect(TUTORIAL_QUICKSTART_EXCEL_B).toContain('/tutorial/')
    })
  })

  describe('TUTORIAL_QUICKSTART_WORD', () => {
    it('is a non-empty string path', () => {
      expect(TUTORIAL_QUICKSTART_WORD).toContain('/tutorial/')
      expect(TUTORIAL_QUICKSTART_WORD).toMatch(/\.docx$/)
    })
  })

  describe('TUTORIAL_SAMPLE_NAME_PREFIX', () => {
    it('is the tutorial sample prefix', () => {
      expect(TUTORIAL_SAMPLE_NAME_PREFIX).toBe('教程示例-')
    })
  })

  describe('trackTutorialOfficeUploadPath', () => {
    it('stores a file path in sessionStorage', () => {
      trackTutorialOfficeUploadPath('/path/to/file.xlsx')
      expect(readTutorialOfficeUploadPaths()).toContain('/path/to/file.xlsx')
    })

    it('does not duplicate paths', () => {
      trackTutorialOfficeUploadPath('/path/to/file.xlsx')
      trackTutorialOfficeUploadPath('/path/to/file.xlsx')
      expect(readTutorialOfficeUploadPaths()).toEqual(['/path/to/file.xlsx'])
    })

    it('appends new paths to existing list', () => {
      trackTutorialOfficeUploadPath('/path/a.xlsx')
      trackTutorialOfficeUploadPath('/path/b.xlsx')
      expect(readTutorialOfficeUploadPaths()).toEqual(['/path/a.xlsx', '/path/b.xlsx'])
    })

    it('does nothing for empty string', () => {
      trackTutorialOfficeUploadPath('')
      expect(readTutorialOfficeUploadPaths()).toEqual([])
    })

    it('keeps at most 12 paths', () => {
      for (let i = 0; i < 15; i++) {
        trackTutorialOfficeUploadPath(`/path/${i}.xlsx`)
      }
      const paths = readTutorialOfficeUploadPaths()
      expect(paths).toHaveLength(12)
      expect(paths[0]).toBe('/path/3.xlsx')
    })
  })

  describe('readTutorialOfficeUploadPaths', () => {
    it('returns empty array when sessionStorage is empty', () => {
      expect(readTutorialOfficeUploadPaths()).toEqual([])
    })

    it('returns stored paths', () => {
      trackTutorialOfficeUploadPath('/path/file.xlsx')
      expect(readTutorialOfficeUploadPaths()).toEqual(['/path/file.xlsx'])
    })
  })

  describe('clearTutorialOfficeUploadPaths', () => {
    it('removes all stored paths', () => {
      trackTutorialOfficeUploadPath('/path/a.xlsx')
      trackTutorialOfficeUploadPath('/path/b.xlsx')
      clearTutorialOfficeUploadPaths()
      expect(readTutorialOfficeUploadPaths()).toEqual([])
    })

    it('does not throw when sessionStorage is already empty', () => {
      expect(() => clearTutorialOfficeUploadPaths()).not.toThrow()
    })
  })
})
