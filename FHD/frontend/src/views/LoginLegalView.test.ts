import { mount, flushPromises } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CORE_ROUTES } from '@/router/routes/core'
import { resolveInitialRoutes } from '@/router/initialRouteSelection'
import { LEGAL_DOCUMENTS } from '@/constants/legalDocuments'

const mode = vi.hoisted(() => ({ shell: false }))
vi.mock('@/utils/adminConsoleUrl', () => ({ isAdminConsoleSpa: () => false }))
vi.mock('@/constants/platformShellMode', async importOriginal => ({
  ...await importOriginal<typeof import('@/constants/platformShellMode')>(),
  isPlatformShellModeEnabled: () => mode.shell,
}))
afterEach(() => { mode.shell = false; window.history.replaceState({}, '', '/'); document.title = '' })

describe('login legal documents', () => {
  it.each(['normal', 'shell', 'sandbox'])('can read all local documents before login in %s mode and return without losing the destination', async variant => {
    mode.shell = variant === 'shell'
    window.history.replaceState({}, '', variant === 'sandbox' ? '/?sandbox' : '/')
    const router = createRouter({ history: createMemoryHistory(), routes: resolveInitialRoutes(CORE_ROUTES) })
    const wrapper = mount({ template: '<RouterView />' }, { global: { plugins: [router] } })
    try {
      for (const kind of ['service-agreement', 'privacy-policy', 'model-recipients'] as const) {
        await router.push({ name: 'login-legal', params: { document: kind }, query: { redirect: '/business-docking' } })
        await flushPromises()
        expect(router.currentRoute.value.meta).toMatchObject({ publicAccess: true, hideChrome: true })
        expect(wrapper.get('h1').text()).toBe(LEGAL_DOCUMENTS[kind].title)
        expect(wrapper.text()).toContain('版本 2026-11-01')
        expect(wrapper.text()).not.toContain('生效日期')
        expect(wrapper.findAll('section')).toHaveLength(kind === 'service-agreement' ? 7 : 8)
        expect(wrapper.text()).not.toMatch(/\*\*|\]\(https:\/\//)
        expect(wrapper.get('a[href="mailto:970882904@qq.com"]').text()).toBe('隐私联系：970882904@qq.com')
        for (const unverified of ['审阅草案', '发布前待确认', 'support@xiu-ci.com', '所有数据均存储于企业自有服务器']) {
          expect(wrapper.text()).not.toContain(unverified)
        }
        const documentLinks = wrapper.get('nav[aria-label="协议与隐私政策"]').findAll('a')
        expect(documentLinks.map(link => link.text())).toEqual(['XCMAX 服务协议', 'XCMAX 隐私政策'])
        expect(documentLinks.find(link => link.attributes('aria-current') === 'page')?.text()).toBe(LEGAL_DOCUMENTS[kind].title)
        expect(wrapper.text()).not.toContain('XCMAX 当前平台模型接收方')
        if (kind === 'service-agreement') {
          const emphasized = wrapper.findAll('strong').map(item => item.text())
          expect(emphasized).toContain('平台模型调用计费，并非默认免费。')
          expect(emphasized).toContain('AI 结果可能存在遗漏、误识别或不准确内容。')
        }
        if (kind !== 'service-agreement') {
          expect(wrapper.text()).toContain('十五个工作日内答复处理结果或说明仍需核实的事项')
          expect(wrapper.text()).toContain('原始上传文件目前设有7天到期时间')
          expect(wrapper.text()).toContain('不是到点立即执行的定时删除保证')
          expect(wrapper.text()).toContain('独立的手动保留机制')
          expect(wrapper.text()).toContain('创建时间超过90天')
          expect(wrapper.text()).toContain('此规则不代表运行概要')
          expect(wrapper.find('a[href="https://privacy.mi.com/support"]').exists()).toBe(true)
          expect(wrapper.findAll('table tr')).toHaveLength(13)
          expect(wrapper.text()).toContain('模型接收方及变更')
          expect(wrapper.text()).toContain('平台使用其配置凭据调用')
          expect(wrapper.text()).toContain('用户点击登录不能替代供应商许可')
          expect(wrapper.text()).toContain('北京小米移动软件有限公司及其关联公司')
          expect(wrapper.text()).toContain('中国集群')
          for (const url of ['https://token-plan-cn.xiaomimimo.com/v1', 'https://privacy.mi.com/support', 'https://privacy.mi.com/XiaomiMiMoPlatform/zh_CN/']) {
            expect(wrapper.get(`a[href="${url}"]`).attributes('rel')).toBe('noopener noreferrer')
          }
        }
        expect(wrapper.get('a').attributes('href')).toBe('/login?redirect=/business-docking')
        expect(document.title).toContain(LEGAL_DOCUMENTS[kind].title)
        expect(wrapper.find('[role=dialog]').exists()).toBe(false)
        expect(wrapper.find('input[type=checkbox]').exists()).toBe(false)
      }
    } finally { wrapper.unmount() }
  })
})
