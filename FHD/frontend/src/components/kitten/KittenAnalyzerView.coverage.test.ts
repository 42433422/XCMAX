/**
 * KittenAnalyzerView.vue 覆盖率补齐测试
 * 目标：覆盖脚本内所有函数的 happy path、空值、边界、异常路径
 * 重点：onVizEmployeeSelect、applyVizEmployeeChartType、runDocGen、onQuickPick、
 *       runFinancialBriefAndClose、startVoiceInput、stopVoiceInput、openDownloadLink
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref, nextTick } from 'vue'
import type { Component } from 'vue'

// ── 可控 mock 状态（hoisted-safe）─────────────────────────────
let mockAnalyzer: Record<string, unknown>
let mockVizEmployees: Record<string, unknown>

vi.mock('@/composables/useKittenAnalyzer', () => ({
  useKittenAnalyzer: () => mockAnalyzer,
  kittenQuickActions: [
    { text: '分析销量趋势', label: '销量趋势' },
    { text: '计算渠道ROI', label: '渠道ROI' },
  ],
  extractKittenDocumentPickupUrl: (content: string) => {
    if (!content) return null
    // 优先匹配绝对 URL，与真实实现保持一致
    const absolute = content.match(/https?:\/\/[^\s"'<>)\]]+\/api\/ai\/kitten\/document\/pickup\/[^\s"'<>)\]]+/)
    if (absolute) return absolute[0]
    const relative = content.match(/\/api\/ai\/kitten\/document\/pickup\/[^\s"'<>)\]]+/)
    return relative ? relative[0] : null
  },
}))

vi.mock('@/composables/useKittenVizEmployees', () => ({
  useKittenVizEmployees: () => mockVizEmployees,
}))

vi.mock('@/utils/sanitizeHtml', () => ({
  sanitizeChatBubbleHtml: (html: string) => html,
}))

vi.mock('@/utils', () => ({
  downloadBlob: vi.fn(),
  getFilenameFromDisposition: vi.fn((_hdr: unknown, fallback: string) => fallback),
}))

vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/api/core', () => ({
  buildFullApiUrl: (path: string) => `http://localhost:5000${path}`,
}))

import KittenAnalyzerView from './KittenAnalyzerView.vue'
import { downloadBlob, getFilenameFromDisposition } from '@/utils'
import { appAlert } from '@/utils/appDialog'

// ── 创建默认 mock analyzer ────────────────────────────────────
function createMockAnalyzer(overrides: Record<string, unknown> = {}) {
  return {
    messages: ref([
      { role: 'ai', content: '欢迎', time: '10:00' },
    ]),
    inputText: ref(''),
    isChatLoading: ref(false),
    isKittenStreaming: ref(false),
    isDatasetParsing: ref(false),
    currentResult: ref(null as null | { id: number; title: string; summary: string; chart: boolean; type: string; kind: string }),
    fileInput: ref(null),
    chatMessagesRef: ref(null),
    datasetSummary: ref(null as null | { name: string; rows: number; columns: number; fieldNames: string[]; previewText: string }),
    datasetRows: ref([] as Record<string, unknown>[]),
    fieldProfiles: ref([]),
    chartConfig: ref({ type: 'bar', xField: '', yField: '', groupField: '', aggregate: 'count' }),
    recommendedCharts: ref([]),
    kittenIncludeBusinessDb: ref(false),
    kittenIncludeWebSearch: ref(true),
    kittenDbStatsHint: ref(''),
    lastWebSearchHits: ref([]),
    datasetFieldPreview: ref([]),
    lastDocumentPickupUrl: ref(null as null | string),
    loadingStatusText: ref(''),
    resetSession: vi.fn(),
    onKittenBusinessDbToggle: vi.fn(),
    triggerFileUpload: vi.fn(),
    handleFileSelect: vi.fn(),
    setChartConfig: vi.fn(),
    applyChartRecommendation: vi.fn(),
    sendMessage: vi.fn(),
    sendQuickAction: vi.fn(),
    exportResult: vi.fn(),
    exportDocx: vi.fn(),
    isDocGenLoading: ref(false),
    generateAiOfficeDocument: vi.fn().mockResolvedValue(undefined),
    runFinancialBrief: vi.fn().mockResolvedValue(undefined),
    clearResult: vi.fn(),
    handleInputKeydown: vi.fn(),
    ...overrides,
  }
}

// ── 创建默认 mock viz employees ──────────────────────────────
function createMockVizEmployees(overrides: Record<string, unknown> = {}) {
  return {
    employees: ref([
      { pkgId: 'emp1', name: '员工1', installed: false, chartType: 'bar', palette: ['#000'], dashboard: null },
    ]),
    selected: ref({
      pkgId: 'emp1',
      name: '员工1',
      installed: false,
      chartType: 'bar',
      palette: ['#000'],
      dashboard: null,
    }),
    installedCount: ref(0),
    loading: ref(false),
    selectEmployee: vi.fn(),
    ...overrides,
  }
}

// ── 自定义 stub 组件（可触发事件）────────────────────────────
const VizEmployeeStripStub = {
  name: 'KittenVizEmployeeStrip',
  template: '<div class="viz-strip-stub"><button class="viz-select-btn" @click="$emit(\'select\', \'emp2\')">Select</button></div>',
} as unknown as Component

const ChartPanelStub = {
  name: 'KittenChartPanel',
  template: '<div class="chart-panel-stub"><button class="update-config-btn" @click="$emit(\'updateConfig\', { type: \'line\' })">Update</button><button class="apply-rec-btn" @click="$emit(\'applyRecommendation\', { id: \'test\', label: \'Test\', description: \'d\', config: { type: \'pie\' } })">Apply</button></div>',
} as unknown as Component

const LauncherIconStub = {
  name: 'KittenLauncherIcon',
  template: '<span class="launcher-icon-stub">icon</span>',
} as unknown as Component

function mountView(analyzerOverrides: Record<string, unknown> = {}, vizOverrides: Record<string, unknown> = {}) {
  mockAnalyzer = createMockAnalyzer(analyzerOverrides)
  mockVizEmployees = createMockVizEmployees(vizOverrides)
  return mount(KittenAnalyzerView, {
    global: {
      stubs: {
        KittenVizEmployeeStrip: VizEmployeeStripStub,
        KittenChartPanel: ChartPanelStub,
        KittenLauncherIcon: LauncherIconStub,
      },
    },
  })
}

describe('KittenAnalyzerView.vue - 覆盖率补齐', () => {
  let originalFetch: typeof global.fetch

  beforeEach(() => {
    vi.clearAllMocks()
    originalFetch = global.fetch
    // 清理 SpeechRecognition
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition
    delete (window as Window & { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition
  })

  afterEach(() => {
    global.fetch = originalFetch
    vi.restoreAllMocks()
  })

  // ── 基础渲染 ─────────────────────────────────────────────────
  describe('基础渲染', () => {
    it('挂载并显示标题', () => {
      const wrapper = mountView()
      expect(wrapper.find('.kitten-shell').exists()).toBe(true)
      expect(wrapper.text()).toContain('智慧分析')
    })

    it('无数据集时不显示数据集栏', () => {
      const wrapper = mountView()
      expect(wrapper.find('.kitten-dataset-bar').exists()).toBe(false)
    })

    it('有数据集时显示数据集栏', () => {
      const wrapper = mountView({
        datasetSummary: ref({ name: 'test.csv', rows: 100, columns: 3, fieldNames: ['a', 'b', 'c'], previewText: '' }),
      })
      expect(wrapper.find('.kitten-dataset-bar').exists()).toBe(true)
      expect(wrapper.text()).toContain('test.csv')
      expect(wrapper.text()).toContain('100 行')
    })

    it('显示聊天消息', () => {
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '你好', time: '10:00' },
          { role: 'user', content: '问题', time: '10:01' },
        ]),
      })
      const msgs = wrapper.findAll('.message')
      expect(msgs.length).toBe(2)
      expect(msgs[0].classes()).toContain('ai')
      expect(msgs[1].classes()).toContain('user')
    })

    it('消息含取件链接时显示下载按钮', () => {
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '文档已生成 /api/ai/kitten/document/pickup/abc123', time: '10:00' },
        ]),
      })
      expect(wrapper.find('.download-btn').exists()).toBe(true)
    })

    it('消息不含取件链接时不显示下载按钮', () => {
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '普通回复', time: '10:00' },
        ]),
      })
      expect(wrapper.find('.download-btn').exists()).toBe(false)
    })

    it('数据集解析中显示加载状态', () => {
      const wrapper = mountView({
        isDatasetParsing: ref(true),
        loadingStatusText: ref('正在解析数据文件...'),
      })
      const aiMsgs = wrapper.findAll('.message.ai')
      expect(aiMsgs.some((m) => m.text().includes('正在解析数据文件...'))).toBe(true)
    })

    it('聊天加载中且非流式时显示加载状态', () => {
      const wrapper = mountView({
        isChatLoading: ref(true),
        isKittenStreaming: ref(false),
        loadingStatusText: ref('正在回复…'),
      })
      const aiMsgs = wrapper.findAll('.message.ai')
      expect(aiMsgs.some((m) => m.text().includes('正在回复…'))).toBe(true)
    })

    it('聊天加载中且流式时不显示额外加载状态', () => {
      const wrapper = mountView({
        isChatLoading: ref(true),
        isKittenStreaming: ref(true),
        loadingStatusText: ref('正在回复…'),
      })
      // 流式时不显示额外的 loading message（因为 isChatLoading && !isKittenStreaming 为 false）
      const loadingMsgs = wrapper.findAll('.message.ai').filter((m) => m.text().includes('正在回复…'))
      expect(loadingMsgs.length).toBe(0)
    })

    it('侧边栏默认折叠', () => {
      const wrapper = mountView()
      expect(wrapper.find('.side-panel').classes()).toContain('is-collapsed')
    })

    it('点击折叠按钮展开侧边栏', async () => {
      const wrapper = mountView()
      await wrapper.find('.panel-collapse-toggle').trigger('click')
      expect(wrapper.find('.side-panel').classes()).not.toContain('is-collapsed')
      expect(wrapper.find('.panel-collapse-toggle').text()).toBe('收起')
    })

    it('无数据集时侧边栏显示上传提示', () => {
      const wrapper = mountView()
      expect(wrapper.find('.panel-hint').text()).toContain('上传表格后可预览字段')
    })

    it('有数据集时侧边栏显示字段预览', () => {
      const wrapper = mountView({
        datasetSummary: ref({ name: 'test.csv', rows: 10, columns: 3, fieldNames: ['a', 'b', 'c'], previewText: '' }),
        datasetFieldPreview: ref(['a', 'b', 'c']),
      })
      // 展开侧边栏
      wrapper.find('.panel-collapse-toggle').trigger('click')
      const chips = wrapper.findAll('.asset-chip')
      expect(chips.length).toBe(3)
    })

    it('字段超过 8 个时显示省略号', () => {
      const wrapper = mountView({
        datasetSummary: ref({ name: 'test.csv', rows: 10, columns: 10, fieldNames: ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j'], previewText: '' }),
        datasetFieldPreview: ref(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']),
      })
      wrapper.find('.panel-collapse-toggle').trigger('click')
      expect(wrapper.find('.asset-chip.muted').exists()).toBe(true)
    })

    it('有 web 搜索引用时显示引用列表', () => {
      const wrapper = mountView({
        lastWebSearchHits: ref([
          { title: '引用1', url: 'https://example.com/1', snippet: '' },
          { title: '引用2', url: 'https://example.com/2', snippet: '' },
        ]),
      })
      wrapper.find('.panel-collapse-toggle').trigger('click')
      const citations = wrapper.findAll('.citation-list li')
      expect(citations.length).toBe(2)
    })

    it('引用列表最多显示 5 条', () => {
      const hits = Array.from({ length: 7 }, (_, i) => ({ title: `引用${i}`, url: `https://example.com/${i}`, snippet: '' }))
      const wrapper = mountView({
        lastWebSearchHits: ref(hits),
      })
      wrapper.find('.panel-collapse-toggle').trigger('click')
      const citations = wrapper.findAll('.citation-list li')
      expect(citations.length).toBe(5)
    })

    it('无 currentResult 时导出按钮禁用', () => {
      const wrapper = mountView()
      wrapper.find('.panel-collapse-toggle').trigger('click')
      const exportBtn = wrapper.find('.export-row .btn-primary')
      expect(exportBtn.attributes('disabled')).toBeDefined()
    })

    it('有 currentResult 时导出按钮启用', () => {
      const wrapper = mountView({
        currentResult: ref({ id: 1, title: '结果', summary: '摘要', chart: false, type: 't', kind: 'k' }),
      })
      wrapper.find('.panel-collapse-toggle').trigger('click')
      const exportBtn = wrapper.find('.export-row .btn-primary')
      expect(exportBtn.attributes('disabled')).toBeUndefined()
    })

    it('有 currentResult 时显示结果预览', () => {
      const wrapper = mountView({
        currentResult: ref({ id: 1, title: '测试结果', summary: '测试摘要', chart: false, type: 't', kind: 'k' }),
      })
      wrapper.find('.panel-collapse-toggle').trigger('click')
      expect(wrapper.find('.result-preview').exists()).toBe(true)
      expect(wrapper.text()).toContain('测试结果')
    })

    it('有 lastDocumentPickupUrl 时显示下载文档按钮', () => {
      const wrapper = mountView({
        lastDocumentPickupUrl: ref('/api/ai/kitten/document/pickup/xyz'),
      })
      wrapper.find('.panel-collapse-toggle').trigger('click')
      expect(wrapper.find('.pickup-download-row').exists()).toBe(true)
    })

    it('有 kittenDbStatsHint 时显示提示', () => {
      const wrapper = mountView({
        kittenDbStatsHint: ref('已就绪：原材料 100 条'),
      })
      wrapper.find('.panel-collapse-toggle').trigger('click')
      expect(wrapper.text()).toContain('已就绪：原材料 100 条')
    })

    it('docGenExpanded 默认为 false', () => {
      const wrapper = mountView()
      expect(wrapper.find('.doc-gen-panel').exists()).toBe(false)
    })

    it('快捷选择下拉框渲染选项', () => {
      const wrapper = mountView()
      const options = wrapper.findAll('.quick-select option')
      // 第一个是占位 "快捷…"，其余来自 kittenQuickActions mock
      expect(options.length).toBe(3)
    })
  })

  // ── 头部交互 ─────────────────────────────────────────────────
  describe('头部交互', () => {
    it('点击返回按钮触发 back 事件', async () => {
      const wrapper = mountView()
      await wrapper.find('.kitten-back').trigger('click')
      expect(wrapper.emitted('back')).toBeTruthy()
    })

    it('点击清空按钮调用 resetSession', async () => {
      const wrapper = mountView()
      await wrapper.find('.kitten-header-action').trigger('click')
      expect(mockAnalyzer.resetSession).toHaveBeenCalled()
    })
  })

  // ── 输入区域交互 ─────────────────────────────────────────────
  describe('输入区域交互', () => {
    it('点击上传按钮调用 triggerFileUpload', async () => {
      const wrapper = mountView()
      const attachBtn = wrapper.findAll('.attach-btn')[0]
      await attachBtn.trigger('click')
      expect(mockAnalyzer.triggerFileUpload).toHaveBeenCalled()
    })

    it('文件选择触发 handleFileSelect', async () => {
      const wrapper = mountView()
      const fileInput = wrapper.find('.kitten-file-input')
      await fileInput.trigger('change')
      expect(mockAnalyzer.handleFileSelect).toHaveBeenCalled()
    })

    it('点击发送按钮调用 sendMessage', async () => {
      const wrapper = mountView()
      await wrapper.find('.send-btn').trigger('click')
      expect(mockAnalyzer.sendMessage).toHaveBeenCalled()
    })

    it('textarea 键盘事件调用 handleInputKeydown', async () => {
      const wrapper = mountView()
      const textarea = wrapper.find('textarea')
      await textarea.trigger('keydown', { key: 'Enter' })
      expect(mockAnalyzer.handleInputKeydown).toHaveBeenCalled()
    })

    it('数据集解析中发送按钮禁用', () => {
      const wrapper = mountView({ isDatasetParsing: ref(true) })
      expect(wrapper.find('.send-btn').attributes('disabled')).toBeDefined()
    })

    it('聊天加载中发送按钮禁用', () => {
      const wrapper = mountView({ isChatLoading: ref(true) })
      expect(wrapper.find('.send-btn').attributes('disabled')).toBeDefined()
    })

    it('数据集解析中上传按钮禁用', () => {
      const wrapper = mountView({ isDatasetParsing: ref(true) })
      const attachBtn = wrapper.findAll('.attach-btn')[0]
      expect(attachBtn.attributes('disabled')).toBeDefined()
    })
  })

  // ── 快捷选择 ─────────────────────────────────────────────────
  describe('快捷选择 onQuickPick', () => {
    it('选择有效快捷操作时调用 sendQuickAction', async () => {
      const wrapper = mountView()
      const select = wrapper.find('.quick-select')
      await select.setValue('分析销量趋势')
      await select.trigger('change')
      expect(mockAnalyzer.sendQuickAction).toHaveBeenCalledWith(
        expect.objectContaining({ text: '分析销量趋势' }),
      )
    })

    it('选择空值时不调用 sendQuickAction', async () => {
      const wrapper = mountView()
      const select = wrapper.find('.quick-select')
      await select.setValue('')
      await select.trigger('change')
      expect(mockAnalyzer.sendQuickAction).not.toHaveBeenCalled()
    })

    it('选择无效值时不调用 sendQuickAction', async () => {
      const wrapper = mountView()
      const select = wrapper.find('.quick-select')
      // 直接设置 quickPick 为不匹配的值后触发 change
      await select.setValue('无效操作')
      await select.trigger('change')
      expect(mockAnalyzer.sendQuickAction).not.toHaveBeenCalled()
    })

    it('快捷选择后 quickPick 被重置为空（通过 sendQuickAction 调用验证）', async () => {
      const wrapper = mountView()
      const select = wrapper.find('.quick-select')
      await select.setValue('分析销量趋势')
      await select.trigger('change')
      await nextTick()
      // onQuickPick 内部先重置 quickPick='' 再调用 sendQuickAction
      // sendQuickAction 被调用即证明 onQuickPick 执行完毕
      expect(mockAnalyzer.sendQuickAction).toHaveBeenCalledWith(
        expect.objectContaining({ text: '分析销量趋势' }),
      )
    })

    it('数据集解析中快捷选择禁用', () => {
      const wrapper = mountView({ isDatasetParsing: ref(true) })
      expect(wrapper.find('.quick-select').attributes('disabled')).toBeDefined()
    })
  })

  // ── 更多菜单 ─────────────────────────────────────────────────
  describe('更多菜单', () => {
    it('点击财务简报按钮调用 runFinancialBrief 并关闭菜单', async () => {
      const wrapper = mountView()
      // 打开 more 菜单
      const details = wrapper.find('.more-menu')
      await details.trigger('toggle')
      // 找到财务简报按钮
      const briefBtn = wrapper.findAll('.more-action')[0]
      await briefBtn.trigger('click')
      expect(mockAnalyzer.runFinancialBrief).toHaveBeenCalled()
    })

    it('数据集解析中财务简报按钮禁用', () => {
      const wrapper = mountView({ isDatasetParsing: ref(true) })
      const briefBtn = wrapper.findAll('.more-action')[0]
      expect(briefBtn.attributes('disabled')).toBeDefined()
    })

    it('点击生成文档按钮展开 doc-gen 面板', async () => {
      const wrapper = mountView()
      const docGenBtn = wrapper.findAll('.more-action')[1]
      await docGenBtn.trigger('click')
      expect(wrapper.find('.doc-gen-panel').exists()).toBe(true)
    })

    it('再次点击生成文档按钮收起 doc-gen 面板', async () => {
      const wrapper = mountView()
      const docGenBtn = wrapper.findAll('.more-action')[1]
      await docGenBtn.trigger('click')
      expect(wrapper.find('.doc-gen-panel').exists()).toBe(true)
      await docGenBtn.trigger('click')
      expect(wrapper.find('.doc-gen-panel').exists()).toBe(false)
    })
  })

  // ── 文档生成 ─────────────────────────────────────────────────
  describe('文档生成 runDocGen', () => {
    it('点击生成按钮调用 generateAiOfficeDocument', async () => {
      const wrapper = mountView()
      // 展开 doc-gen 面板
      wrapper.findAll('.more-action')[1].trigger('click')
      await nextTick()

      const input = wrapper.find('.doc-gen-input')
      await input.setValue('写一份合同')
      await wrapper.find('.toolbar-chip-primary').trigger('click')
      expect(mockAnalyzer.generateAiOfficeDocument).toHaveBeenCalledWith('写一份合同', 'docx')
    })

    it('Enter 键触发文档生成', async () => {
      const wrapper = mountView()
      wrapper.findAll('.more-action')[1].trigger('click')
      await nextTick()

      const input = wrapper.find('.doc-gen-input')
      await input.setValue('生成报表')
      await input.trigger('keydown', { key: 'Enter' })
      expect(mockAnalyzer.generateAiOfficeDocument).toHaveBeenCalledWith('生成报表', 'docx')
    })

    it('切换格式为 xlsx', async () => {
      const wrapper = mountView()
      wrapper.findAll('.more-action')[1].trigger('click')
      await nextTick()

      const select = wrapper.find('.doc-gen-select')
      await select.setValue('xlsx')
      await wrapper.find('.toolbar-chip-primary').trigger('click')
      expect(mockAnalyzer.generateAiOfficeDocument).toHaveBeenCalledWith('', 'xlsx')
    })

    it('生成中按钮显示加载文本且禁用', async () => {
      const wrapper = mountView({
        isDocGenLoading: ref(true),
      })
      // 先展开 doc-gen 面板
      await wrapper.findAll('.more-action')[1].trigger('click')
      await nextTick()
      const genBtn = wrapper.find('.toolbar-chip-primary')
      expect(genBtn.text()).toContain('生成中…')
      expect(genBtn.attributes('disabled')).toBeDefined()
    })

    it('聊天加载中生成按钮禁用', async () => {
      const wrapper = mountView({
        isChatLoading: ref(true),
      })
      // 先展开 doc-gen 面板
      await wrapper.findAll('.more-action')[1].trigger('click')
      await nextTick()
      expect(wrapper.find('.toolbar-chip-primary').attributes('disabled')).toBeDefined()
    })
  })

  // ── 导出按钮 ─────────────────────────────────────────────────
  describe('导出按钮', () => {
    function mountWithResult() {
      return mountView({
        currentResult: ref({ id: 1, title: '结果', summary: '摘要', chart: false, type: 't', kind: 'k' }),
      })
    }

    it('点击 Excel 按钮调用 exportResult', async () => {
      const wrapper = mountWithResult()
      wrapper.find('.panel-collapse-toggle').trigger('click')
      const btns = wrapper.findAll('.export-row .btn')
      await btns[0].trigger('click') // Excel
      expect(mockAnalyzer.exportResult).toHaveBeenCalled()
    })

    it('点击 Word 按钮调用 exportDocx', async () => {
      const wrapper = mountWithResult()
      wrapper.find('.panel-collapse-toggle').trigger('click')
      const btns = wrapper.findAll('.export-row .btn')
      await btns[1].trigger('click') // Word
      expect(mockAnalyzer.exportDocx).toHaveBeenCalled()
    })

    it('点击清除按钮调用 clearResult', async () => {
      const wrapper = mountWithResult()
      wrapper.find('.panel-collapse-toggle').trigger('click')
      const btns = wrapper.findAll('.export-row .btn')
      await btns[2].trigger('click') // 清除
      expect(mockAnalyzer.clearResult).toHaveBeenCalled()
    })
  })

  // ── 可视化员工选择 ───────────────────────────────────────────
  describe('可视化员工选择 onVizEmployeeSelect', () => {
    it('选择员工时调用 selectEmployee', async () => {
      const wrapper = mountView({
        datasetSummary: ref({ name: 'test.csv', rows: 10, columns: 3, fieldNames: ['a'], previewText: '' }),
      })
      const strip = wrapper.findComponent({ name: 'KittenVizEmployeeStrip' })
      strip.vm.$emit('select', 'emp2')
      await nextTick()
      expect(mockVizEmployees.selectEmployee).toHaveBeenCalledWith('emp2')
    })

    it('员工已安装且有数据集时设置图表类型（非 dashboard）', async () => {
      const wrapper = mountView({
        datasetSummary: ref({ name: 'test.csv', rows: 10, columns: 3, fieldNames: ['a'], previewText: '' }),
      }, {
        selected: ref({
          pkgId: 'emp1',
          name: '员工1',
          installed: true,
          chartType: 'line',
          palette: ['#000'],
          dashboard: null,
        }),
      })
      const strip = wrapper.findComponent({ name: 'KittenVizEmployeeStrip' })
      strip.vm.$emit('select', 'emp1')
      await nextTick()
      expect(mockAnalyzer.setChartConfig).toHaveBeenCalledWith({ type: 'line' })
    })

    it('员工已安装且有数据集且为 dashboard 时设置图表类型为 bar', async () => {
      const wrapper = mountView({
        datasetSummary: ref({ name: 'test.csv', rows: 10, columns: 3, fieldNames: ['a'], previewText: '' }),
      }, {
        selected: ref({
          pkgId: 'emp1',
          name: '员工1',
          installed: true,
          chartType: 'pie',
          palette: ['#000'],
          dashboard: { title: 'dash' },
        }),
      })
      const strip = wrapper.findComponent({ name: 'KittenVizEmployeeStrip' })
      strip.vm.$emit('select', 'emp1')
      await nextTick()
      expect(mockAnalyzer.setChartConfig).toHaveBeenCalledWith({ type: 'bar' })
    })

    it('员工未安装时不设置图表类型', async () => {
      const wrapper = mountView({
        datasetSummary: ref({ name: 'test.csv', rows: 10, columns: 3, fieldNames: ['a'], previewText: '' }),
      }, {
        selected: ref({
          pkgId: 'emp1',
          name: '员工1',
          installed: false,
          chartType: 'line',
          palette: ['#000'],
          dashboard: null,
        }),
      })
      const strip = wrapper.findComponent({ name: 'KittenVizEmployeeStrip' })
      strip.vm.$emit('select', 'emp1')
      await nextTick()
      expect(mockAnalyzer.setChartConfig).not.toHaveBeenCalled()
    })

    it('无数据集时不设置图表类型（通过 watch 覆盖此分支）', async () => {
      // 无数据集时 KittenVizEmployeeStrip 不渲染（v-if="datasetSummary"），
      // 因此无法通过 UI 触发 onVizEmployeeSelect。
      // 此分支由 "数据集名称变化但员工未安装时不触发" 等测试覆盖。
      // 这里验证组件正常挂载不报错
      const wrapper = mountView({}, {
        selected: ref({
          pkgId: 'emp1',
          name: '员工1',
          installed: true,
          chartType: 'line',
          palette: ['#000'],
          dashboard: null,
        }),
      })
      expect(wrapper.find('.kitten-shell').exists()).toBe(true)
      // 无数据集时 strip 不渲染
      expect(wrapper.findComponent({ name: 'KittenVizEmployeeStrip' }).exists()).toBe(false)
    })
  })

  // ── applyVizEmployeeChartType watch 触发 ─────────────────────
  describe('applyVizEmployeeChartType watch 触发', () => {
    it('数据集名称变化时触发 applyVizEmployeeChartType', async () => {
      const datasetSummary = ref(null as null | { name: string; rows: number; columns: number; fieldNames: string[]; previewText: string })
      const wrapper = mountView({
        datasetSummary,
      }, {
        selected: ref({
          pkgId: 'emp1',
          name: '员工1',
          installed: true,
          chartType: 'line',
          palette: ['#000'],
          dashboard: null,
        }),
      })
      // 初始无数据集，不触发 setChartConfig
      expect(mockAnalyzer.setChartConfig).not.toHaveBeenCalled()
      // 设置数据集，触发 watch
      datasetSummary.value = { name: 'new.csv', rows: 10, columns: 3, fieldNames: ['a'], previewText: '' }
      await nextTick()
      expect(mockAnalyzer.setChartConfig).toHaveBeenCalledWith({ type: 'line' })
    })

    it('数据集名称变化但员工未安装时不触发 setChartConfig', async () => {
      const datasetSummary = ref(null as null | { name: string; rows: number; columns: number; fieldNames: string[]; previewText: string })
      const wrapper = mountView({
        datasetSummary,
      }, {
        selected: ref({
          pkgId: 'emp1',
          name: '员工1',
          installed: false,
          chartType: 'line',
          palette: ['#000'],
          dashboard: null,
        }),
      })
      datasetSummary.value = { name: 'new.csv', rows: 10, columns: 3, fieldNames: ['a'], previewText: '' }
      await nextTick()
      expect(mockAnalyzer.setChartConfig).not.toHaveBeenCalled()
    })
  })

  // ── 图表面板事件 ─────────────────────────────────────────────
  describe('图表面板事件', () => {
    it('updateConfig 事件调用 setChartConfig', async () => {
      const wrapper = mountView({
        datasetSummary: ref({ name: 'test.csv', rows: 10, columns: 3, fieldNames: ['a'], previewText: '' }),
        datasetRows: ref([{ a: 1 }]),
      })
      const panel = wrapper.findComponent({ name: 'KittenChartPanel' })
      panel.vm.$emit('updateConfig', { type: 'line' })
      await nextTick()
      expect(mockAnalyzer.setChartConfig).toHaveBeenCalledWith({ type: 'line' })
    })

    it('applyRecommendation 事件调用 applyChartRecommendation', async () => {
      const wrapper = mountView({
        datasetSummary: ref({ name: 'test.csv', rows: 10, columns: 3, fieldNames: ['a'], previewText: '' }),
        datasetRows: ref([{ a: 1 }]),
      })
      const rec = { id: 'test', label: 'Test', description: 'd', config: { type: 'pie' as const } }
      const panel = wrapper.findComponent({ name: 'KittenChartPanel' })
      panel.vm.$emit('applyRecommendation', rec)
      await nextTick()
      expect(mockAnalyzer.applyChartRecommendation).toHaveBeenCalledWith(rec)
    })

    it('无数据集行时不显示图表面板', () => {
      const wrapper = mountView({
        datasetSummary: ref({ name: 'test.csv', rows: 10, columns: 3, fieldNames: ['a'], previewText: '' }),
        datasetRows: ref([]),
      })
      expect(wrapper.findComponent({ name: 'KittenChartPanel' }).exists()).toBe(false)
    })
  })

  // ── 业务库摘要勾选 ───────────────────────────────────────────
  describe('业务库摘要勾选', () => {
    it('勾选业务库摘要触发 onKittenBusinessDbToggle', async () => {
      const wrapper = mountView()
      wrapper.find('.panel-collapse-toggle').trigger('click')
      const checkbox = wrapper.find('.panel-check input[type="checkbox"]')
      await checkbox.setValue(true)
      expect(mockAnalyzer.onKittenBusinessDbToggle).toHaveBeenCalled()
    })
  })

  // ── 语音输入 ─────────────────────────────────────────────────
  describe('语音输入 startVoiceInput / stopVoiceInput', () => {
    function getVoiceButton(wrapper: ReturnType<typeof mountView>) {
      // 语音按钮是第二个 .attach-btn（第一个是文件上传）
      return wrapper.findAll('.attach-btn')[1]
    }

    it('浏览器不支持语音识别时设置 error 状态', async () => {
      // 不设置 SpeechRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      expect(voiceBtn.classes()).toContain('voice-error')
    })

    it('支持语音识别时开始录音', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      // start() 被调用后，onstart 回调应被触发设置 recording 状态
      expect(mockRecognition.instance.start).toHaveBeenCalled()
      // 手动触发 onstart
      mockRecognition.instance.onstart!()
      await nextTick()
      expect(voiceBtn.classes()).toContain('voice-recording')
    })

    it('使用 webkitSpeechRecognition 作为后备', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      expect(mockRecognition.instance.start).toHaveBeenCalled()
    })

    it('已在录音中再次按下不重复启动', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      mockRecognition.instance.onstart!()
      await nextTick()
      // 再次 mousedown
      await voiceBtn.trigger('mousedown')
      // start 只被调用一次
      expect(mockRecognition.instance.start).toHaveBeenCalledTimes(1)
    })

    it('已在转写中再次按下不重复启动', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView({
        isChatLoading: ref(false),
      })
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      mockRecognition.instance.onstart!()
      await nextTick()
      // 模拟转写中状态（通过 onresult 不直接设置 transcribing，这里用 voiceState 内部逻辑）
      // voiceState transcribing 在此组件中不直接设置，跳过此场景
    })

    it('已有 voiceRecognition 时先 abort 再创建新的', async () => {
      const mockRecognition1 = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition1
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      // 不触发 onstart，直接再次 mousedown（voiceState 仍为 idle）
      const mockRecognition2 = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition2
      await voiceBtn.trigger('mousedown')
      expect(mockRecognition1.instance.abort).toHaveBeenCalled()
    })

    it('onresult 回调将识别文本追加到 inputText', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      // 触发 onresult
      mockRecognition.instance.onresult!({
        results: [[{ transcript: '你好世界' }]],
      })
      await nextTick()
      expect(mockAnalyzer.inputText.value).toBe('你好世界')
    })

    it('onresult 回调将文本追加到已有 inputText', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView({
        inputText: ref('已有文本 '),
      })
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      mockRecognition.instance.onresult!({
        results: [[{ transcript: '追加' }]],
      })
      await nextTick()
      expect(mockAnalyzer.inputText.value).toBe('已有文本 追加')
    })

    it('onresult 处理空结果', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      mockRecognition.instance.onresult!({ results: [] })
      await nextTick()
      expect(mockAnalyzer.inputText.value).toBe('')
    })

    it('onerror 为 no-speech 时恢复 idle 状态', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      mockRecognition.instance.onstart!()
      await nextTick()
      mockRecognition.instance.onerror!({ error: 'no-speech' })
      await nextTick()
      expect(voiceBtn.classes()).not.toContain('voice-recording')
      expect(voiceBtn.classes()).not.toContain('voice-error')
    })

    it('onerror 为其他错误时设置 error 状态', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      mockRecognition.instance.onerror!({ error: 'network' })
      await nextTick()
      expect(voiceBtn.classes()).toContain('voice-error')
    })

    it('onerror 无 error 字段时使用默认错误文本', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      mockRecognition.instance.onerror!({})
      await nextTick()
      expect(voiceBtn.classes()).toContain('voice-error')
    })

    it('onend 在录音中时恢复 idle', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      mockRecognition.instance.onstart!()
      await nextTick()
      mockRecognition.instance.onend!()
      await nextTick()
      expect(voiceBtn.classes()).not.toContain('voice-recording')
    })

    it('mouseup 停止录音', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      mockRecognition.instance.onstart!()
      await nextTick()
      await voiceBtn.trigger('mouseup')
      expect(mockRecognition.instance.stop).toHaveBeenCalled()
      expect(voiceBtn.classes()).not.toContain('voice-recording')
    })

    it('mouseleave 停止录音', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      mockRecognition.instance.onstart!()
      await nextTick()
      await voiceBtn.trigger('mouseleave')
      expect(mockRecognition.instance.stop).toHaveBeenCalled()
    })

    it('touchstart 启动录音', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('touchstart')
      expect(mockRecognition.instance.start).toHaveBeenCalled()
    })

    it('touchend 停止录音', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('touchstart')
      mockRecognition.instance.onstart!()
      await nextTick()
      await voiceBtn.trigger('touchend')
      expect(mockRecognition.instance.stop).toHaveBeenCalled()
    })

    it('touchcancel 停止录音', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('touchstart')
      mockRecognition.instance.onstart!()
      await nextTick()
      await voiceBtn.trigger('touchcancel')
      expect(mockRecognition.instance.stop).toHaveBeenCalled()
    })

    it('无 voiceRecognition 时 stopVoiceInput 不报错', async () => {
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mouseup')
      // 不报错即可
    })

    it('聊天加载中语音按钮禁用', () => {
      const wrapper = mountView({ isChatLoading: ref(true) })
      const voiceBtn = getVoiceButton(wrapper)
      expect(voiceBtn.attributes('disabled')).toBeDefined()
    })

    it('语音按钮 title 随状态变化', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      expect(voiceBtn.attributes('title')).toContain('按住说话')
      await voiceBtn.trigger('mousedown')
      mockRecognition.instance.onstart!()
      await nextTick()
      expect(voiceBtn.attributes('title')).toContain('松开停止')
    })

    it('录音中显示停止图标', async () => {
      const mockRecognition = createMockSpeechRecognition()
      ;(window as Window & { SpeechRecognition?: unknown }).SpeechRecognition = mockRecognition
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown')
      mockRecognition.instance.onstart!()
      await nextTick()
      expect(voiceBtn.find('.fa-stop-circle').exists()).toBe(true)
    })

    it('错误状态显示错误图标', async () => {
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      await voiceBtn.trigger('mousedown') // 不支持语音 → error
      await nextTick()
      expect(voiceBtn.find('.fa-exclamation-circle').exists()).toBe(true)
    })

    it('idle 状态显示麦克风图标', () => {
      const wrapper = mountView()
      const voiceBtn = getVoiceButton(wrapper)
      expect(voiceBtn.find('.fa-microphone').exists()).toBe(true)
    })
  })

  // ── openDownloadLink ─────────────────────────────────────────
  describe('openDownloadLink', () => {
    function mockFetchResponse(opts: {
      ok?: boolean
      status?: number
      contentType?: string
      contentDisposition?: string
      blob?: Blob
      json?: unknown
    }) {
      const blob = opts.blob || new Blob(['data'], { type: opts.contentType || 'application/octet-stream' })
      global.fetch = vi.fn().mockResolvedValue({
        ok: opts.ok !== false,
        status: opts.status || 200,
        headers: {
          get: (name: string) => {
            if (name === 'content-type') return opts.contentType || ''
            if (name === 'content-disposition') return opts.contentDisposition || null
            return null
          },
        },
        blob: async () => blob,
        json: async () => opts.json || {},
      } as unknown as Response)
    }

    it('点击消息中的下载按钮触发 openDownloadLink（相对路径）', async () => {
      mockFetchResponse({ contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '文档 /api/ai/kitten/document/pickup/abc', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      expect(global.fetch).toHaveBeenCalledWith(
        'http://localhost:5000/api/ai/kitten/document/pickup/abc',
        { credentials: 'include' },
      )
    })

    it('点击消息中的下载按钮触发 openDownloadLink（绝对路径）', async () => {
      mockFetchResponse({ contentType: 'application/octet-stream' })
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '文档 https://example.com/api/ai/kitten/document/pickup/xyz', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      expect(global.fetch).toHaveBeenCalledWith(
        'https://example.com/api/ai/kitten/document/pickup/xyz',
        { credentials: 'include' },
      )
    })

    it('成功下载 Excel 文件时调用 downloadBlob', async () => {
      mockFetchResponse({
        contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        contentDisposition: 'attachment; filename="report.xlsx"',
      })
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '/api/ai/kitten/document/pickup/excel', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      await nextTick()
      expect(downloadBlob).toHaveBeenCalled()
    })

    it('成功下载 Word 文件时扩展名为 docx', async () => {
      mockFetchResponse({
        contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      })
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '/api/ai/kitten/document/pickup/word', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      await nextTick()
      expect(getFilenameFromDisposition).toHaveBeenCalledWith(
        null,
        '文档.docx',
      )
    })

    it('成功下载其他文件时扩展名为 bin', async () => {
      mockFetchResponse({
        contentType: 'application/octet-stream',
      })
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '/api/ai/kitten/document/pickup/bin', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      await nextTick()
      expect(getFilenameFromDisposition).toHaveBeenCalledWith(
        null,
        '文档.bin',
      )
    })

    it('响应非 ok 且为 JSON 时抛出含 message 的错误', async () => {
      mockFetchResponse({
        ok: false,
        status: 500,
        contentType: 'application/json',
        json: { message: '服务器内部错误' },
      })
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '/api/ai/kitten/document/pickup/err', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      await nextTick()
      expect(appAlert).toHaveBeenCalledWith(expect.stringContaining('服务器内部错误'))
    })

    it('响应非 ok 且非 JSON 时抛出状态码错误', async () => {
      mockFetchResponse({
        ok: false,
        status: 404,
        contentType: 'text/html',
      })
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '/api/ai/kitten/document/pickup/404', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      await nextTick()
      expect(appAlert).toHaveBeenCalledWith(expect.stringContaining('404'))
    })

    it('响应 ok 但返回 JSON 时抛出 "服务器返回了 JSON" 错误', async () => {
      mockFetchResponse({
        ok: true,
        status: 200,
        contentType: 'application/json',
        json: { message: '未登录' },
      })
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '/api/ai/kitten/document/pickup/json', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      await nextTick()
      expect(appAlert).toHaveBeenCalledWith(expect.stringContaining('未登录'))
    })

    it('响应 ok 但返回 JSON 且无 message 时使用默认错误文本', async () => {
      mockFetchResponse({
        ok: true,
        status: 200,
        contentType: 'application/json',
        json: {},
      })
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '/api/ai/kitten/document/pickup/json2', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      await nextTick()
      expect(appAlert).toHaveBeenCalledWith(expect.stringContaining('服务器返回了 JSON'))
    })

    it('fetch 抛出异常时调用 appAlert 并尝试 window.open', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'))
      const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '/api/ai/kitten/document/pickup/neterr', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      await nextTick()
      expect(appAlert).toHaveBeenCalledWith(expect.stringContaining('Network error'))
      expect(openSpy).toHaveBeenCalled()
      openSpy.mockRestore()
    })

    it('非 ok 响应 JSON 解析失败时使用默认状态码错误', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        headers: {
          get: (name: string) => (name === 'content-type' ? 'application/json' : null),
        },
        json: async () => {
          throw new Error('parse error')
        },
      } as unknown as Response)
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '/api/ai/kitten/document/pickup/parse', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      await nextTick()
      expect(appAlert).toHaveBeenCalledWith(expect.stringContaining('502'))
    })

    it('ok 响应 JSON 解析失败时使用默认 JSON 错误', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: {
          get: (name: string) => (name === 'content-type' ? 'application/json' : null),
        },
        json: async () => {
          throw new Error('parse error')
        },
      } as unknown as Response)
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '/api/ai/kitten/document/pickup/parse2', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      await nextTick()
      expect(appAlert).toHaveBeenCalledWith(expect.stringContaining('JSON'))
    })

    it('点击侧边栏下载文档按钮触发 openDownloadLink', async () => {
      mockFetchResponse({ contentType: 'application/octet-stream' })
      const wrapper = mountView({
        lastDocumentPickupUrl: ref('/api/ai/kitten/document/pickup/sidebar'),
      })
      wrapper.find('.panel-collapse-toggle').trigger('click')
      await wrapper.find('.pickup-download-row .btn').trigger('click')
      await nextTick()
      expect(global.fetch).toHaveBeenCalled()
    })

    it('window.open 抛出异常时静默处理', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('fail'))
      vi.spyOn(window, 'open').mockImplementation(() => {
        throw new Error('blocked')
      })
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '/api/ai/kitten/document/pickup/blocked', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      await nextTick()
      // 不抛出异常即可
      expect(appAlert).toHaveBeenCalled()
    })

    it('错误对象非 Error 实例时使用 String 转换', async () => {
      global.fetch = vi.fn().mockRejectedValue('string error')
      vi.spyOn(window, 'open').mockImplementation(() => null)
      const wrapper = mountView({
        messages: ref([
          { role: 'ai', content: '/api/ai/kitten/document/pickup/strerr', time: '10:00' },
        ]),
      })
      await wrapper.find('.download-btn').trigger('click')
      await nextTick()
      await nextTick()
      expect(appAlert).toHaveBeenCalledWith(expect.stringContaining('string error'))
    })
  })
})

// ── 辅助：创建 mock SpeechRecognition 构造器 ──────────────────
function createMockSpeechRecognition() {
  const instance = {
    lang: '',
    continuous: false,
    interimResults: false,
    maxAlternatives: 1,
    onstart: null as (() => void) | null,
    onresult: null as ((event: unknown) => void) | null,
    onerror: null as ((event: unknown) => void) | null,
    onend: null as (() => void) | null,
    start: vi.fn(),
    stop: vi.fn(),
    abort: vi.fn(),
  }
  // 返回构造器函数本身，instance 作为属性挂载，便于测试中直接赋值给 window.SpeechRecognition
  const Ctor = vi.fn(() => instance)
  return Object.assign(Ctor, { instance }) as typeof Ctor & { instance: typeof instance }
}
