import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter, type RouteRecordRaw } from 'vue-router'

const LayoutStub = { template: '<router-view />' }
const ViewStub = { template: '<div />' }

/** 与 router/index.ts 中 AI 测试相关片段保持一致，用于 redirect 行为回归。 */
const aiTestRoutes: RouteRecordRaw[] = [
  {
    path: '/ai-test',
    component: LayoutStub,
    children: [
      { path: '', redirect: { name: 'ai-test-sandbox' } },
      { path: 'sandbox', name: 'ai-test-sandbox', component: ViewStub },
      { path: 'exam', name: 'ai-test-exam', component: ViewStub },
    ],
  },
  { path: '/sandbox', name: 'sandbox', redirect: { name: 'ai-test-sandbox' } },
]

describe('AI test routes', () => {
  it('redirects /sandbox to ai-test-sandbox', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: aiTestRoutes })
    await router.push('/sandbox')
    await router.isReady()
    expect(router.currentRoute.value.name).toBe('ai-test-sandbox')
    expect(router.currentRoute.value.path).toBe('/ai-test/sandbox')
  })

  it('redirects /ai-test to ai-test-sandbox', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: aiTestRoutes })
    await router.push('/ai-test')
    await router.isReady()
    expect(router.currentRoute.value.name).toBe('ai-test-sandbox')
  })

  it('resolves ai-test-exam', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: aiTestRoutes })
    await router.push('/ai-test/exam')
    await router.isReady()
    expect(router.currentRoute.value.name).toBe('ai-test-exam')
  })
})
