import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, reactive } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { printApi, type LabelJobResponse } from '@/api/print'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { buildLabelPrintHostUpdate } from '@/workflow/coreWorkflowDispatcher'
import { mergeCorePayloadFromExisting } from '@/workflow/coreWorkflowMonitor'
import LabelJobReview from './LabelJobReview.vue'
import WorkflowLabelPreviewLink from './WorkflowLabelPreviewLink.vue'
import PrintView from '../../../mods/xcagi-erp-domain-bridge/frontend/views/PrintView.vue'

const scope = reactive({ activeModId: '' })
vi.mock('@/stores/mods', () => ({ useModsStore: () => scope }))
const job = { id: 'a'.repeat(32), status: 'generated' as const, message: '已有标签预览', product_id: 2, product_name: '指定产品', template_id: 'db:42', template_name: '指定模板', copies: 3, paper_width_mm: 90, paper_height_mm: 60 }
let wrapper: VueWrapper | undefined
function button(text: string) { return wrapper!.findAll('button').find(b => b.text() === text)! }
beforeEach(() => {
  scope.activeModId = ''
  vi.spyOn(printApi, 'getLabelJob').mockResolvedValue({ success: true, job })
  vi.spyOn(printApi, 'downloadLabelJob').mockImplementation(async () => new Response('%PDF-1.7 fixture', { headers: { 'Content-Type': 'application/pdf' } }))
  vi.spyOn(printApi, 'confirmLabelJob').mockResolvedValue({ success: true, job, confirm_token: 'confirmation-token', confirm_prompt: '确认 3 张标签与打印机？' })
  vi.spyOn(printApi, 'submitLabelJob').mockResolvedValue({ success: true, job: { ...job, status: 'submitted', message: '已提交打印队列' } })
  vi.spyOn(printApi, 'generateLabelJob')
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:owned-label'), revokeObjectURL: vi.fn() }))
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('owned label preview continuation', () => {
  it('opens the actual Mod print view from a workflow link and submits only after confirmation', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/print', component: PrintView },
      { path: '/mod/xcagi-erp-domain-bridge/print', component: PrintView },
    ] })
    await router.push('/')
    const saved = JSON.parse(JSON.stringify(buildLabelPrintHostUpdate({ jobId: job.id, line: '预览已生成' })))
    const restored = mergeCorePayloadFromExisting('label_print', undefined, saved)
    const Shell = defineComponent({ components: { WorkflowLabelPreviewLink, RouterView }, setup: () => ({ id: restored.lastLabelPrint?.jobId }), template: '<WorkflowLabelPreviewLink :job-id="id" /><RouterView />' })
    wrapper = mount(Shell, { global: { plugins: [router] } })
    await wrapper.get('a').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.label_job).toBe(job.id)
    expect(wrapper.text()).toContain('指定产品 · 指定模板 · 3 张')
    expect(wrapper.find('iframe').attributes('src')).toBe('blob:owned-label')
    expect(printApi.generateLabelJob).not.toHaveBeenCalled()
    expect(printApi.submitLabelJob).not.toHaveBeenCalled()
    await button('准备打印').trigger('click'); await flushPromises()
    expect(printApi.submitLabelJob).not.toHaveBeenCalled()
    await button('确认并提交打印').trigger('click'); await flushPromises()
    expect(printApi.submitLabelJob).toHaveBeenCalledExactlyOnceWith(job.id, 'confirmation-token')
    expect(wrapper.text()).toContain('已提交打印队列')
    expect(button('准备打印').attributes('disabled')).toBeDefined()
  })

  it.each(['account', 'mod', 'unmount'])('discards a pending old job after %s changes', async change => {
    let finish!: (value: LabelJobResponse) => void
    vi.mocked(printApi.getLabelJob).mockImplementationOnce(() => new Promise(resolve => { finish = resolve })).mockRejectedValue(new Error('任务不可访问'))
    wrapper = mount(LabelJobReview, { props: { jobId: job.id } })
    if (change === 'account') productReadAccountEpoch.value++
    if (change === 'mod') { scope.activeModId = 'another'; scope.activeModId = '' }
    if (change === 'unmount') wrapper.unmount()
    finish({ success: true, job }); await flushPromises()
    expect(URL.createObjectURL).not.toHaveBeenCalled()
    expect(printApi.downloadLabelJob).not.toHaveBeenCalled()
  })

  it('clears an existing preview and confirmation when account changes', async () => {
    wrapper = mount(LabelJobReview, { props: { jobId: job.id } }); await flushPromises()
    await button('准备打印').trigger('click'); await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    vi.mocked(printApi.getLabelJob).mockRejectedValue(new Error('无权读取'))
    productReadAccountEpoch.value++; await flushPromises()
    expect(wrapper.find('iframe').exists()).toBe(false)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:owned-label')
    expect(printApi.submitLabelJob).not.toHaveBeenCalled()
  })

  it('requires queue reconciliation after ambiguous submission', async () => {
    vi.mocked(printApi.submitLabelJob).mockRejectedValue(new Error('连接中断'))
    wrapper = mount(LabelJobReview, { props: { jobId: job.id } }); await flushPromises()
    await button('准备打印').trigger('click'); await flushPromises()
    await button('确认并提交打印').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('提交结果待确认')
    expect(button('准备打印').attributes('disabled')).toBeDefined()
    expect(printApi.submitLabelJob).toHaveBeenCalledTimes(1)
  })

  it('rejects invalid identifiers before fetching', async () => {
    wrapper = mount(LabelJobReview, { props: { jobId: '../private-file' } }); await flushPromises()
    expect(wrapper.text()).toContain('编号无效')
    expect(printApi.getLabelJob).not.toHaveBeenCalled()
  })

  it('does not enable confirmation for an invalid PDF', async () => {
    vi.mocked(printApi.downloadLabelJob).mockResolvedValue(new Response('<html>login</html>', { headers: { 'Content-Type': 'text/html' } }))
    wrapper = mount(LabelJobReview, { props: { jobId: job.id } }); await flushPromises()
    expect(wrapper.text()).toContain('PDF 响应无效')
    expect(button('准备打印').attributes('disabled')).toBeDefined()
  })
})
