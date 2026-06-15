import {
  TUTORIAL_DEPT_EMPLOYEE_SAMPLE_XLSX,
  TUTORIAL_SAMPLE_NAME_PREFIX,
} from '@/constants/tutorialSamples'
import type { TutorialStep } from './types'
import { createStep } from './stepFactory'

/**
 * 进阶教程末尾：智能对话基础用法 → 办公员工包装齐后 → Excel 导入库 → 清理教学样本。
 */
export function buildChatExcelWorkflowSteps(): TutorialStep[] {
  const sampleFile = TUTORIAL_DEPT_EMPLOYEE_SAMPLE_XLSX
  const prefix = TUTORIAL_SAMPLE_NAME_PREFIX

  return [
    createStep({
      id: 'chat-dialogue-basics',
      title: '智能对话 · 简单用法',
      description:
        '顶部快捷话术可一键发送常见指令；也可在输入框自由提问（如「你能帮我做什么？」），点「发送」或 Enter。办公员工包装齐后，助手可调用表格读取等工具。',
      routeName: 'chat',
      targetSelector: '[data-tour="chat-quick-actions"]',
      highlightSelector: '[data-tour="chat-input-area"]',
      actionType: 'observe',
      track: 'advanced',
      excludeInPro: false,
      allowCardNext: true,
    }),
    createStep({
      id: 'tutorial-excel-sample',
      title: '教学样本 Excel',
      description: `本步使用含「部门」「人员」两张工作表的教学文件（行名均以「${prefix}」开头，便于事后清理）。请在新标签页打开 ${sampleFile} 下载到本机，稍后在对话页上传。`,
      routeName: 'chat',
      targetSelector: '[data-tour="chat-input-area"]',
      highlightSelector: '#view-chat button[data-tutorial-id="toolbar-excel-analyze"]',
      actionType: 'observe',
      track: 'advanced',
      excludeInPro: false,
      allowCardNext: true,
    }),
    createStep({
      id: 'tutorial-excel-upload',
      title: '分析 Excel',
      description: `点击「分析 Excel」上传刚下载的样本。解析完成后在输入区上方选择工作表「部门」或「人员」。`,
      routeName: 'chat',
      targetSelector: '#view-chat button[data-tutorial-id="toolbar-excel-analyze"]',
      highlightSelector: '#view-chat button[data-tutorial-id="toolbar-excel-analyze"]',
      actionType: 'click',
      track: 'advanced',
      excludeInPro: false,
      allowCardNext: true,
    }),
    createStep({
      id: 'tutorial-excel-import-customers',
      title: '导入部门到数据库',
      description: `关联工作表选「部门」，在输入框发送：「导入数据库，类型客户，确认导入」。若提示写入令牌，按界面指引输入 DB 写入授权后重试。`,
      routeName: 'chat',
      targetSelector: '#messageInput',
      highlightSelector: '#view-chat .input-wrapper',
      actionType: 'observe',
      track: 'advanced',
      excludeInPro: false,
      allowCardNext: true,
    }),
    createStep({
      id: 'tutorial-excel-import-products',
      title: '导入人员到数据库',
      description: `切换关联工作表为「人员」，发送：「导入数据库，类型产品，确认导入」。系统会按「产品单位」「产品名称」列写入人员/产品表。`,
      routeName: 'chat',
      targetSelector: '#messageInput',
      highlightSelector: '#view-chat .sheet-link-bar, #view-chat .input-wrapper',
      actionType: 'observe',
      track: 'advanced',
      excludeInPro: false,
      allowCardNext: true,
    }),
    createStep({
      id: 'tutorial-verify-departments',
      title: '验收 · 部门/客户',
      description: `打开侧栏「组织管理 / 部门管理 / 客户管理」（名称因行业而异）。搜索「${prefix}」应能看到 2 条教学部门。`,
      targetSelector: '.sidebar .menu-item[data-view="customers"]',
      actionType: 'click',
      routeName: 'customers',
      track: 'advanced',
      excludeInPro: false,
      allowCardNext: true,
    }),
    createStep({
      id: 'tutorial-cleanup-departments',
      title: '清理教学部门',
      description: `勾选名称含「${prefix}」的行，点顶栏「批量删除」移除教学部门。仅删样本，不影响真实业务数据。`,
      routeName: 'customers',
      targetSelector: '#view-customers .card',
      highlightSelector: '#view-customers .customers-header-actions',
      actionType: 'observe',
      track: 'advanced',
      excludeInPro: false,
      allowCardNext: true,
    }),
    createStep({
      id: 'tutorial-verify-employees',
      title: '验收 · 人员/产品',
      description: `打开侧栏「业务对象 / 人员管理 / 产品管理」。在单位下拉选「${prefix}市场部」，应看到 2 条教学人员；「${prefix}研发部」另有 1 条。`,
      targetSelector: '.sidebar .menu-item[data-view="products"]',
      actionType: 'click',
      routeName: 'products',
      track: 'advanced',
      excludeInPro: false,
      allowCardNext: true,
    }),
    createStep({
      id: 'tutorial-cleanup-employees',
      title: '清理教学人员',
      description: `在人员/产品列表勾选「${prefix}」开头的行，点「批量删除」。两个教学单位下的样本都删完后，本教程导入演练即完成。`,
      routeName: 'products',
      targetSelector: '#view-products .card',
      highlightSelector: '#view-products .page-header',
      actionType: 'observe',
      track: 'advanced',
      excludeInPro: false,
      allowCardNext: true,
    }),
    createStep({
      id: 'tutorial-excel-flow-complete',
      title: '导入演练完成',
      description:
        '完整流程：智能对话 → 分析 Excel → 导入部门与客户库、人员与产品库 → 列表验收 → 批量删除教学样本。日常业务请使用真实表格并同样可在对话中导入。',
      routeName: 'chat',
      targetSelector: '[data-tour="chat-thread"]',
      highlightSelector: '[data-tour="chat-input-area"]',
      actionType: 'observe',
      track: 'advanced',
      excludeInPro: false,
    }),
  ]
}
