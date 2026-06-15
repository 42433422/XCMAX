import { describe, it, expect } from 'vitest'
import {
  TEMPLATE_MEDIA_KINDS,
  TEMPLATE_MEDIA_LABELS,
  TEMPLATE_MEDIA_ORDER,
  TEMPLATE_MEDIA_ACCEPT,
  isTemplateMediaKind,
  normalizeTemplateMediaKind,
  templateMediaKindFromFilename,
  templateMediaIconClass,
  templateMediaCardClass,
  templateMediaUploadHint,
} from './templateMediaKinds'

describe('templateMediaKinds', () => {
  it('TEMPLATE_MEDIA_KINDS contains expected kinds', () => {
    expect(TEMPLATE_MEDIA_KINDS).toContain('excel')
    expect(TEMPLATE_MEDIA_KINDS).toContain('word')
    expect(TEMPLATE_MEDIA_KINDS).toContain('csv')
    expect(TEMPLATE_MEDIA_KINDS).toContain('ppt')
    expect(TEMPLATE_MEDIA_KINDS).toContain('pdf')
  })

  it('TEMPLATE_MEDIA_LABELS has labels for all kinds', () => {
    for (const kind of TEMPLATE_MEDIA_KINDS) {
      expect(TEMPLATE_MEDIA_LABELS[kind]).toBeTruthy()
    }
  })

  it('TEMPLATE_MEDIA_ORDER has all kinds', () => {
    expect(TEMPLATE_MEDIA_ORDER).toHaveLength(5)
  })

  it('TEMPLATE_MEDIA_ACCEPT contains expected extensions', () => {
    expect(TEMPLATE_MEDIA_ACCEPT).toContain('.xlsx')
    expect(TEMPLATE_MEDIA_ACCEPT).toContain('.docx')
    expect(TEMPLATE_MEDIA_ACCEPT).toContain('.pdf')
  })

  it('isTemplateMediaKind returns true for valid kinds', () => {
    expect(isTemplateMediaKind('excel')).toBe(true)
    expect(isTemplateMediaKind('word')).toBe(true)
    expect(isTemplateMediaKind('pdf')).toBe(true)
  })

  it('isTemplateMediaKind returns false for invalid kinds', () => {
    expect(isTemplateMediaKind('invalid')).toBe(false)
    expect(isTemplateMediaKind('')).toBe(false)
    expect(isTemplateMediaKind(123 as any)).toBe(false)
  })

  it('normalizeTemplateMediaKind returns valid kind', () => {
    expect(normalizeTemplateMediaKind('excel')).toBe('excel')
  })

  it('normalizeTemplateMediaKind returns fallback for invalid', () => {
    expect(normalizeTemplateMediaKind('invalid')).toBe('excel')
    expect(normalizeTemplateMediaKind('invalid', 'word')).toBe('word')
  })

  it('templateMediaKindFromFilename detects xlsx', () => {
    expect(templateMediaKindFromFilename('report.xlsx')).toBe('excel')
  })

  it('templateMediaKindFromFilename detects xls', () => {
    expect(templateMediaKindFromFilename('old.xls')).toBe('excel')
  })

  it('templateMediaKindFromFilename detects docx', () => {
    expect(templateMediaKindFromFilename('doc.docx')).toBe('word')
  })

  it('templateMediaKindFromFilename detects csv', () => {
    expect(templateMediaKindFromFilename('data.csv')).toBe('csv')
  })

  it('templateMediaKindFromFilename detects pptx', () => {
    expect(templateMediaKindFromFilename('slides.pptx')).toBe('ppt')
  })

  it('templateMediaKindFromFilename detects pdf', () => {
    expect(templateMediaKindFromFilename('file.pdf')).toBe('pdf')
  })

  it('templateMediaKindFromFilename returns null for unknown extension', () => {
    expect(templateMediaKindFromFilename('image.png')).toBeNull()
  })

  it('templateMediaKindFromFilename returns null for no extension', () => {
    expect(templateMediaKindFromFilename('noext')).toBeNull()
  })

  it('templateMediaKindFromFilename returns null for null input', () => {
    expect(templateMediaKindFromFilename(null)).toBeNull()
  })

  it('templateMediaIconClass returns icon for valid kind', () => {
    expect(templateMediaIconClass('excel')).toBe('fa-file-excel-o')
    expect(templateMediaIconClass('word')).toBe('fa-file-word-o')
  })

  it('templateMediaIconClass returns default for invalid kind', () => {
    expect(templateMediaIconClass('invalid')).toBe('fa-file-o')
  })

  it('templateMediaCardClass returns class for valid kind', () => {
    expect(templateMediaCardClass('excel')).toBe('tp-card--excel')
    expect(templateMediaCardClass('pdf')).toBe('tp-card--pdf')
  })

  it('templateMediaCardClass returns default for invalid kind', () => {
    expect(templateMediaCardClass('invalid')).toBe('tp-card--excel')
  })

  it('templateMediaUploadHint returns hint string', () => {
    const hint = templateMediaUploadHint()
    expect(hint).toContain('Excel')
    expect(hint).toContain('Word')
    expect(hint).toContain('PDF')
  })
})
