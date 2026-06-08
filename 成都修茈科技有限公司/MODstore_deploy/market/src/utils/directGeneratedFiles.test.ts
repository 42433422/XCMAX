import { describe, expect, it } from 'vitest'
import {
  employeeDownloadsToGeneratedFiles,
  filterUserFacingOfficeDownloads,
  softenSandboxDownloadLinks,
} from './directGeneratedFiles'

describe('directGeneratedFiles', () => {
  it('filters internal document_full.json from footer cards', () => {
    const out = filterUserFacingOfficeDownloads([
      { jobId: 'j1', filename: 'document_full.json' },
      { jobId: 'j1', filename: 'out/simplified_contract.docx', label: '简化版合同模板.docx' },
    ])
    expect(out).toHaveLength(1)
    expect(out[0].filename).toContain('simplified_contract.docx')
  })

  it('filters PPT read-phase artifacts from header strip', () => {
    const out = filterUserFacingOfficeDownloads([
      { jobId: 'j1', filename: 'outputs/presentation_full.json' },
      { jobId: 'j1', filename: 'presentation_meta.json' },
      { jobId: 'j1', filename: 'speaker_notes.md' },
      { jobId: 'j1', filename: 'images_index.json' },
      { jobId: 'j1', filename: 's1_img1.vlm.json' },
      { jobId: 'j1', filename: 'out/课堂作业_已完成.pptx', label: '课堂作业.pptx' },
    ])
    expect(out).toHaveLength(1)
    expect(out[0].filename).toContain('.pptx')
  })

  it('maps downloads to generated file cards', () => {
    const cards = employeeDownloadsToGeneratedFiles([
      { jobId: 'j2', filename: 'report.xlsx', label: '销售表' },
    ])
    expect(cards[0].name).toBe('销售表')
    expect(cards[0].status).toBe('ready')
    expect(cards[0].role).toBe('generated')
  })

  it('keeps generated_document.docx as a user-facing card', () => {
    const cards = employeeDownloadsToGeneratedFiles([
      { jobId: 'j3', filename: 'generated_document.docx', label: 'generated_document.docx' },
    ])
    expect(cards).toHaveLength(1)
    expect(cards[0].filename).toBe('generated_document.docx')
  })

  it('softens sandbox markdown download links', () => {
    const raw =
      '已完成。\n\n[下载：简化版合同模板.docx](sandbox:/mnt/data/simplified_contract.docx)'
    const out = softenSandboxDownloadLinks(raw)
    expect(out).not.toMatch(/sandbox:/i)
    expect(out).toContain('见下方文件卡片')
  })
})
