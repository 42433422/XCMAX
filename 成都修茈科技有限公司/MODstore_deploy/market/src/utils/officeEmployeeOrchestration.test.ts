import { describe, expect, it } from 'vitest'
import {
  assistantGaveManualOfficeStepsOnly,
  assistantImpliesPendingFileGeneration,
  classifyOfficeTask,
  detectOfficeDocumentCreateIntent,
  collectOfficeAttachmentNamesFromMessages,
  detectOfficeEnhanceAttachedIntent,
  detectOfficeGenerateIntent,
  detectUserMissingDeliverableComplaint,
  officeFormatFromFileName,
  officeGenerateMissingInputMessage,
  resolveGenerateEmployeeForFormat,
  shouldHandleAsOfficeTask,
  shouldRecoverOfficeGenerate,
  starterRequiresAttachment,
} from './officeEmployeeOrchestration'
import { pickGenerateFormat } from './officeEmployeeRunner'

describe('officeEmployeeOrchestration', () => {
  it('maps word docx to word format', () => {
    expect(officeFormatFromFileName('report.docx')).toBe('word')
    expect(resolveGenerateEmployeeForFormat('word')).toBe('word-generate-employee')
  })

  it('classifies generate with attachment', () => {
    expect(classifyOfficeTask('请生成可下载的 Word 文档', ['a.docx'])).toBe('generate')
  })

  it('classifies generate without attachment', () => {
    expect(classifyOfficeTask('导出 docx 文件', [])).toBe('generate')
  })

  it('classifies analyze with excel attachment', () => {
    expect(classifyOfficeTask('请分析表格数据', ['data.xlsx'])).toBe('analyze')
  })

  it('classifies sales contract without 生成 keyword as generate', () => {
    expect(detectOfficeDocumentCreateIntent('通用销售合同')).toBe(true)
    expect(classifyOfficeTask('通用销售合同', [])).toBe('generate')
    expect(classifyOfficeTask('按模板出一份销售合同', ['tpl.docx'])).toBe('generate')
  })

  it('does not treat contract Q&A as generate', () => {
    expect(detectOfficeDocumentCreateIntent('这份合同第三条是什么意思')).toBe(false)
    expect(detectOfficeDocumentCreateIntent('有没有生成')).toBe(false)
  })

  it('detects assistant pending-generation phrasing', () => {
    expect(assistantImpliesPendingFileGeneration('正在为你生成文件，稍等')).toBe(true)
    expect(assistantImpliesPendingFileGeneration('正在为你生成带动画效果的PPT文件')).toBe(true)
    expect(assistantImpliesPendingFileGeneration('**步骤 1/1**：正在用生成员工生成 PPT')).toBe(true)
  })

  it('detects generate intent for docx', () => {
    expect(detectOfficeGenerateIntent('帮我生成 docx')?.format).toBe('word')
  })

  it('detects contract create without explicit 生成 keyword', () => {
    expect(detectOfficeGenerateIntent('销售合同')?.format).toBe('word')
    expect(detectOfficeDocumentCreateIntent('通用 Word 模板')).toBe(true)
    expect(classifyOfficeTask('销售合同', [])).toBe('generate')
  })

  it('does not treat status question as generate', () => {
    expect(detectOfficeGenerateIntent('有没有生成')).toBeNull()
    expect(classifyOfficeTask('有没有生成', [])).toBe('none')
  })

  it('treats 完成 + homework pptx as generate', () => {
    expect(detectOfficeGenerateIntent('@附件1 课堂作业_已完成.pptx 完成')).toBeNull()
    expect(
      classifyOfficeTask('@附件1 课堂作业_已完成.pptx 完成', ['课堂作业_已完成.pptx']),
    ).toBe('generate')
  })

  it('does not treat bare 完成 with generic pptx as generate', () => {
    expect(classifyOfficeTask('完成', ['季度汇报.pptx'])).toBe('analyze')
  })

  it('classifies pptx + animation homework as generate', () => {
    expect(
      detectOfficeEnhanceAttachedIntent('给每道课堂练习加跑马灯动画', ['PPT课堂练习作业 (2).pptx']),
    ).toBe(true)
    expect(
      classifyOfficeTask('请给每页作业加跑马灯动画', ['PPT课堂练习作业 (2).pptx']),
    ).toBe('generate')
    expect(classifyOfficeTask('制作幻灯片动画效果', ['a.pptx'])).toBe('generate')
    expect(
      classifyOfficeTask('将图片制作成跑马灯动画', ['PPT课堂练习作业 (2).pptx']),
    ).toBe('generate')
    expect(pickGenerateFormat('将图片制作成跑马灯动画', ['PPT课堂练习作业 (2).pptx'])).toBe('ppt')
  })

  it('recover generate when assistant promised and ppt was in prior turn', () => {
    const msgs = [
      {
        role: 'user',
        content: '请看附件',
        attachments: [{ name: 'PPT课堂练习作业 (2).pptx' }],
      },
      { role: 'assistant', content: '已读懂作业要求…' },
    ]
    expect(collectOfficeAttachmentNamesFromMessages(msgs)).toEqual(['PPT课堂练习作业 (2).pptx'])
    expect(
      classifyOfficeTask('帮我做跑马灯动画', collectOfficeAttachmentNamesFromMessages(msgs)),
    ).toBe('generate')
    expect(
      shouldRecoverOfficeGenerate(
        '好的',
        [],
        collectOfficeAttachmentNamesFromMessages(msgs),
        true,
      ),
    ).toBe(true)
  })

  it('guide-only follow-up stays analyze', () => {
    expect(
      classifyOfficeTask('给我操作指南就好', ['PPT课堂练习作业 (2).pptx']),
    ).toBe('analyze')
  })

  it('classifies @附件 homework pptx 完成 as generate', () => {
    expect(
      classifyOfficeTask('@附件1 PPT课堂练习作业 (2).pptx 完成', ['PPT课堂练习作业 (2).pptx']),
    ).toBe('generate')
  })

  it('uses conversation text for animation intent when current message is 完成', () => {
    const conv = '将 5 张花卉图片和播放按钮做成跑马灯动画'
    expect(
      classifyOfficeTask('完成', ['PPT课堂练习作业 (2).pptx'], { conversationUserText: conv }),
    ).toBe('generate')
  })

  it('detectUserMissingDeliverableComplaint', () => {
    expect(detectUserMissingDeliverableComplaint('还是没有')).toBe(true)
    expect(detectUserMissingDeliverableComplaint('好的谢谢')).toBe(false)
  })

  it('assistantGaveManualOfficeStepsOnly', () => {
    expect(
      assistantGaveManualOfficeStepsOnly('请告知您的偏好。选项 1：手动操作 PowerPoint'),
    ).toBe(true)
  })

  it('still detects explicit generate pptx intent', () => {
    expect(detectOfficeGenerateIntent('请生成一份 pptx 幻灯片')?.format).toBe('ppt')
    expect(classifyOfficeTask('导出 pptx 文件', ['a.pptx'])).toBe('generate')
  })

  it('starterRequiresAttachment flags', () => {
    expect(starterRequiresAttachment('总结文档')).toBe(true)
    expect(starterRequiresAttachment('写方案')).toBe(false)
  })

  it('officeGenerateMissingInputMessage mentions plaintext', () => {
    const msg = officeGenerateMissingInputMessage('word')
    expect(msg).toContain('直接用文字描述')
    expect(msg).toContain('word-generate-employee')
    expect(msg).not.toContain('请先上传源文件')
  })

  it('shouldHandleAsOfficeTask with ready employee file', () => {
    const file = new File(['x'], 't.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' })
    expect(
      shouldHandleAsOfficeTask('总结', [{ name: 't.docx', purpose: 'employee', status: 'ready', file }], null),
    ).toBe(true)
  })
})
