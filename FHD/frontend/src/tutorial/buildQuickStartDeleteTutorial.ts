import type { VisibleNavItem } from '@/composables/useVisibleNavItems'
import type { TutorialStep } from './types'
import { createStep } from './stepFactory'
import { TUTORIAL_SAMPLE_NAME_PREFIX } from '@/constants/tutorialSamples'

function navKeys(visibleNav: VisibleNavItem[]): Set<string> {
  return new Set(visibleNav.map((n) => n.key))
}

/** 导入演示后：在部门管理 / 人员管理里删掉教程样本 */
export function buildQuickStartDeleteTutorialSteps(visibleNav: VisibleNavItem[]): TutorialStep[] {
  const keys = navKeys(visibleNav)
  const hasCustomers = keys.has('customers')
  const hasProducts = keys.has('products')
  if (!hasCustomers && !hasProducts) return []

  const prefix = TUTORIAL_SAMPLE_NAME_PREFIX
  const steps: TutorialStep[] = [
    createStep({
      id: 'quickstart-import-seed-db',
      title: '写入教程样本',
      description: `模拟导入结果：自动在后台写入几条「${prefix}」开头的部门与人员，方便下面演示怎么删。`,
      routeName: 'chat',
      targetSelector: '[data-tour="chat-thread"]',
      actionType: 'observe',
      track: 'advanced',
      excludeInPro: false,
      allowCardNext: true,
    }),
  ]

  if (hasCustomers) {
    const customersLabel =
      visibleNav.find((n) => n.key === 'customers')?.name || '部门管理'
    steps.push(
      createStep({
        id: 'quickstart-delete-customers-nav',
        title: `${customersLabel} · 打开列表`,
        description: `点左侧「${customersLabel}」，找到刚才写入的教程部门。`,
        targetSelector: '[data-tour="sidebar-customers"]',
        highlightSelector: '[data-tour="sidebar-customers"]',
        actionType: 'click',
        routeName: 'customers',
        track: 'advanced',
        excludeInPro: false,
        allowCardNext: true,
      }),
      createStep({
        id: 'quickstart-delete-customers',
        title: `${customersLabel} · 批量删除`,
        description: `勾选名称带「${prefix}」的行，点顶栏「批量删除」并确认。教程也会自动帮你勾上。`,
        routeName: 'customers',
        targetSelector: '[data-tour="customers-table"]',
        highlightSelector: '[data-tour="customers-batch-actions"]',
        actionType: 'observe',
        track: 'advanced',
        excludeInPro: false,
        noAutoSkipWhenMissing: true,
        allowCardNext: true,
      }),
    )
  }

  if (hasProducts) {
    const productsLabel =
      visibleNav.find((n) => n.key === 'products')?.name || '人员管理'
    steps.push(
      createStep({
        id: 'quickstart-delete-products-nav',
        title: `${productsLabel} · 打开列表`,
        description: `点左侧「${productsLabel}」，在单位下拉里选「${prefix}演示单位」，能看到教程人员。`,
        targetSelector: '[data-tour="sidebar-products"]',
        highlightSelector: '[data-tour="sidebar-products"]',
        actionType: 'click',
        routeName: 'products',
        track: 'advanced',
        excludeInPro: false,
        allowCardNext: true,
      }),
      createStep({
        id: 'quickstart-delete-products',
        title: `${productsLabel} · 批量删除`,
        description: `勾选「${prefix}」开头的行，点「批量删除」确认，教程样本就清干净了。`,
        routeName: 'products',
        targetSelector: '[data-tour="products-table"]',
        highlightSelector: '[data-tour="products-batch-actions"]',
        actionType: 'observe',
        track: 'advanced',
        excludeInPro: false,
        noAutoSkipWhenMissing: true,
        allowCardNext: true,
      }),
    )
  }

  steps.push(
    createStep({
      id: 'quickstart-import-cleanup',
      title: '清理对话附件',
      description: '最后新开一轮对话，并删除服务器上的教程上传文件。',
      routeName: 'chat',
      targetSelector: '#newConversationBtn',
      highlightSelector: '#newConversationBtn',
      actionType: 'click',
      track: 'advanced',
      excludeInPro: false,
      allowCardNext: true,
    }),
  )

  return steps
}
