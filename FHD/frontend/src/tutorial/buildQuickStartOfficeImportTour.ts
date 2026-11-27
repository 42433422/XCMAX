import type { TutorialStep } from './types'
import { chatUploadAttachmentSelector, createStep } from './stepFactory'
import { TUTORIAL_SAMPLE_NAME_PREFIX } from '@/constants/tutorialSamples'

/** 办公包装完后：智能对话里试 Excel / Word 导入，展示成功后清理 */
export function buildQuickStartOfficeImportSteps(): TutorialStep[] {
  const prefix = TUTORIAL_SAMPLE_NAME_PREFIX
  return [
    createStep({
      id: 'quickstart-import-go-chat',
      title: '第三步 · 试一下读表格',
      description: '办公包已安装。接下来在「智能对话」上传两个 Excel 样本并查看解析结果。',
      routeName: 'chat',
      targetSelector: '[data-tour="chat-input-area"]',
      highlightSelector: chatUploadAttachmentSelector,
      actionType: 'observe',
      track: 'advanced',
      allowCardNext: true,
    }),
    createStep({
      id: 'quickstart-import-excel-a',
      title: '导入演示 · Excel 样本 A',
      description: `点输入框内的「上传附件」图标并选择「${prefix}产品」表。看对话里是否出现「Excel 读取完成」或「Excel 分析完成」。`,
      routeName: 'chat',
      targetSelector: chatUploadAttachmentSelector,
      actionType: 'click',
      track: 'advanced',
      noAutoSkipWhenMissing: true,
    }),
    createStep({
      id: 'quickstart-import-excel-a-result',
      title: 'Excel A · 解析成功',
      description: '中间对话区应显示字段和行数摘要。确认无误后点「下一步」继续第二个表。',
      routeName: 'chat',
      targetSelector: '[data-tour="chat-thread"]',
      highlightSelector: '[data-tour="chat-thread"]',
      actionType: 'observe',
      track: 'advanced',
      allowCardNext: true,
      noAutoSkipWhenMissing: true,
    }),
    createStep({
      id: 'quickstart-import-excel-b',
      title: '导入演示 · Excel 样本 B',
      description: `点输入框内的「上传附件」图标并选择「${prefix}联系人」表。`,
      routeName: 'chat',
      targetSelector: chatUploadAttachmentSelector,
      actionType: 'click',
      track: 'advanced',
      noAutoSkipWhenMissing: true,
    }),
    createStep({
      id: 'quickstart-import-excel-b-result',
      title: 'Excel B · 解析成功',
      description: '两个 Excel 都成功后，下面再试 Word 读取。',
      routeName: 'chat',
      targetSelector: '[data-tour="chat-thread"]',
      highlightSelector: '[data-tour="chat-thread"]',
      actionType: 'observe',
      track: 'advanced',
      allowCardNext: true,
      noAutoSkipWhenMissing: true,
    }),
    createStep({
      id: 'quickstart-import-word',
      title: '导入演示 · Word 样本',
      description: `调用办公包里的 Word 读取员，解析「${prefix}说明」短文并在对话里展示摘要。`,
      routeName: 'chat',
      targetSelector: '[data-tour="chat-input-area"]',
      highlightSelector: '[data-tour="chat-thread"]',
      actionType: 'observe',
      track: 'advanced',
      noAutoSkipWhenMissing: true,
    }),
    createStep({
      id: 'quickstart-import-word-result',
      title: 'Word · 读取成功',
      description: '对话里应出现「Word 读取完成」和文档摘要。接下来去部门管理、人员管理删掉教程样本。',
      routeName: 'chat',
      targetSelector: '[data-tour="chat-thread"]',
      highlightSelector: '[data-tour="chat-thread"]',
      actionType: 'observe',
      track: 'advanced',
      allowCardNext: true,
      noAutoSkipWhenMissing: true,
    }),
  ]
}
