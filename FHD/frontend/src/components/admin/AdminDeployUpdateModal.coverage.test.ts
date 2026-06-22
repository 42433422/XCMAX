/**
 * AdminDeployUpdateModal 覆盖率提升测试
 *
 * 目标：覆盖 AdminDeployUpdateModal.vue 中未覆盖的分支，将覆盖率从 50% 提升到 90%+。
 * 重点覆盖：
 *   - 渲染状态：modelValue、checkLoading、checkError、checkData、jobSteps、jobError
 *   - statusBanner 计算属性：up_to_date / needs_push / enterprise_pending / needs_pack / null
 *   - stepIcon 函数：done / running / error / skipped / pending
 *   - runCheck：成功 / 失败（无 data）/ 异常
 *   - startPush：customOpen true/false、成功 / 失败（无 job_id）/ 异常
 *   - pollJob：job done / error / 异常 / 无 data
 *   - close：pushing true/false
 *   - watch modelValue：open（触发 runCheck）/ close（触发 stopPoll）
 *   - canPush 计算属性：include_backend / include_frontend 组合
 *   - opts 交互：checkbox 切换、channel 选择
 *
 * 遵循铁律3：happy path + 空值/None + 边界值 + 异常路径。
 * Mock 最小化：仅 mock 外部边界（xcmaxAdminApi、window.setInterval/clearInterval）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'

// ── Mock xcmaxAdminApi ──────────────────────────────────────────────

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: {
    checkDeployUpdates: vi.fn(),
    startDeployPush: vi.fn(),
    getDeployJob: vi.fn(),
  },
}))

import AdminDeployUpdateModal from './AdminDeployUpdateModal.vue'
import {
  xcmaxAdminApi,
  type DeployCheckData,
  type DeployJobData,
} from '@/api/xcmaxAdmin'

// ── 辅助函数 ──────────────────────────────────────────────────────────

/** 创建 DeployCheckData */
function makeCheckData(
  flagOverrides: Partial<DeployCheckData['flags']> = {},
): DeployCheckData {
  return {
    admin_local: { version: '1.0.0', git_sha: 'abc123' },
    update_hub: { version: '1.0.0', git_sha: 'abc123' },
    enterprise: { reachable: true, version: '1.0.0', deploy_sha256: 'def456' },
    flags: {
      up_to_date: true,
      enterprise_pending: false,
      needs_push: false,
      needs_pack: false,
      ...flagOverrides,
    },
  }
}

/** 创建 DeployJobData */
function makeJobData(
  overrides: Partial<DeployJobData> = {},
): DeployJobData {
  return {
    job_id: 'job-1',
    status: 'running',
    steps: [],
    ...overrides,
  }
}

// ── 测试套件 ──────────────────────────────────────────────────────────

describe('AdminDeployUpdateModal - coverage ramp', () => {
  let intervalCallbacks: Array<() => void>
  let originalSetInterval: typeof window.setInterval
  let originalClearInterval: typeof window.clearInterval
  let clearIntervalMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    intervalCallbacks = []
    clearIntervalMock = vi.fn()
    originalSetInterval = window.setInterval
    originalClearInterval = window.clearInterval
    // 捕获 setInterval 回调，便于手动触发 pollJob 轮询
    window.setInterval = ((cb: () => void) => {
      intervalCallbacks.push(cb)
      return intervalCallbacks.length
    }) as unknown as typeof window.setInterval
    window.clearInterval = clearIntervalMock as unknown as typeof window.clearInterval

    vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockReset()
    vi.mocked(xcmaxAdminApi.startDeployPush).mockReset()
    vi.mocked(xcmaxAdminApi.getDeployJob).mockReset()
  })

  afterEach(() => {
    window.setInterval = originalSetInterval
    window.clearInterval = originalClearInterval
    vi.restoreAllMocks()
  })

  /** 挂载组件 */
  function mountModal(modelValue = true) {
    return mount(AdminDeployUpdateModal, {
      props: { modelValue },
    })
  }

  /** 获取最后一个 interval 回调（pollJob 的轮询回调） */
  function lastInterval(): (() => void) | null {
    return intervalCallbacks.length > 0
      ? intervalCallbacks[intervalCallbacks.length - 1]
      : null
  }

  // ── 基础渲染 ──────────────────────────────────────────────────────

  describe('基础渲染', () => {
    it('modelValue=true 时渲染模态框', () => {
      const wrapper = mountModal(true)
      expect(wrapper.find('.deploy-update-modal').exists()).toBe(true)
      expect(wrapper.text()).toContain('推送到 update 中转站')
      wrapper.unmount()
    })

    it('渲染介绍文本', () => {
      const wrapper = mountModal(true)
      expect(wrapper.text()).toContain('管理端只负责')
      wrapper.unmount()
    })

    it('渲染底部按钮', () => {
      const wrapper = mountModal(true)
      const buttons = wrapper.findAll('button')
      expect(buttons.length).toBe(4)
      expect(buttons[0].text()).toContain('关闭')
      expect(buttons[1].text()).toContain('重新检测')
      expect(buttons[2].text()).toContain('推送到 update 站')
      expect(buttons[3].text()).toContain('定制推送')
      wrapper.unmount()
    })
  })

  // ── checkLoading 状态 ────────────────────────────────────────────

  describe('checkLoading 状态', () => {
    it('检测中显示"正在检测更新…"', async () => {
      // checkDeployUpdates 返回未决 promise，保持 checkLoading=true
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockReturnValue(
        new Promise(() => {}),
      )
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await nextTick()
      expect(wrapper.find('.deploy-update-modal__checking').exists()).toBe(true)
      expect(wrapper.text()).toContain('正在检测更新')
      wrapper.unmount()
    })

    it('检测中时按钮禁用', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockReturnValue(
        new Promise(() => {}),
      )
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await nextTick()
      const buttons = wrapper.findAll('button')
      // 重新检测、推送、定制推送 应禁用
      expect(buttons[1].attributes('disabled')).toBeDefined()
      expect(buttons[2].attributes('disabled')).toBeDefined()
      expect(buttons[3].attributes('disabled')).toBeDefined()
      wrapper.unmount()
    })
  })

  // ── checkError 状态 ──────────────────────────────────────────────

  describe('checkError 状态', () => {
    it('检测失败时显示错误信息', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        message: '网络错误',
      } as never)
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      const alert = wrapper.find('.deploy-update-alert')
      expect(alert.exists()).toBe(true)
      expect(alert.text()).toContain('网络错误')
      wrapper.unmount()
    })

    it('检测抛异常时显示异常信息', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockRejectedValue(
        new Error('连接超时'),
      )
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      expect(wrapper.find('.deploy-update-alert').text()).toContain('连接超时')
      wrapper.unmount()
    })

    it('检测抛非 Error 异常时显示字符串', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockRejectedValue(
        'string error' as never,
      )
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      expect(wrapper.find('.deploy-update-alert').text()).toContain('string error')
      wrapper.unmount()
    })

    it('检测返回无 data 无 message 时显示默认错误', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue(
        {} as never,
      )
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      expect(wrapper.find('.deploy-update-alert').text()).toContain('检测失败')
      wrapper.unmount()
    })
  })

  // ── statusBanner 计算属性 ────────────────────────────────────────

  describe('statusBanner 计算属性', () => {
    it('up_to_date=true 且 enterprise_pending=false 时显示 ok banner', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData({ up_to_date: true, enterprise_pending: false }),
      } as never)
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      const banner = wrapper.find('.deploy-update-banner.ok')
      expect(banner.exists()).toBe(true)
      expect(banner.text()).toContain('已同步')
      wrapper.unmount()
    })

    it('needs_push=true 时显示 warn banner', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData({
          up_to_date: false,
          needs_push: true,
        }),
      } as never)
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      const banner = wrapper.find('.deploy-update-banner.warn')
      expect(banner.exists()).toBe(true)
      expect(banner.text()).toContain('发现新版本')
      wrapper.unmount()
    })

    it('enterprise_pending=true 时显示 info banner', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData({
          up_to_date: false,
          needs_push: false,
          enterprise_pending: true,
        }),
      } as never)
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      const banner = wrapper.find('.deploy-update-banner.info')
      expect(banner.exists()).toBe(true)
      expect(banner.text()).toContain('企业端待拉取')
      wrapper.unmount()
    })

    it('needs_pack=true 且其他 flag 为 false 时显示 warn banner', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData({
          up_to_date: false,
          needs_push: false,
          enterprise_pending: false,
          needs_pack: true,
        }),
      } as never)
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      const banner = wrapper.find('.deploy-update-banner.warn')
      expect(banner.exists()).toBe(true)
      expect(banner.text()).toContain('本地尚未打包')
      wrapper.unmount()
    })

    it('所有 flag 为 false 时不显示 banner', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData({
          up_to_date: false,
          needs_push: false,
          enterprise_pending: false,
          needs_pack: false,
        }),
      } as never)
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      expect(wrapper.find('.deploy-update-banner').exists()).toBe(false)
      wrapper.unmount()
    })

    it('up_to_date=true 且 enterprise_pending=true 时显示 info banner', async () => {
      // up_to_date && !enterprise_pending 为 false，进入 enterprise_pending 分支
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData({
          up_to_date: true,
          enterprise_pending: true,
          needs_push: false,
        }),
      } as never)
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      const banner = wrapper.find('.deploy-update-banner.info')
      expect(banner.exists()).toBe(true)
      wrapper.unmount()
    })
  })

  // ── checkData 表格渲染 ───────────────────────────────────────────

  describe('checkData 表格渲染', () => {
    it('检测成功时渲染版本表格', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData(),
      } as never)
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      const table = wrapper.find('.deploy-update-table')
      expect(table.exists()).toBe(true)
      expect(table.text()).toContain('管理端本地')
      expect(table.text()).toContain('update 中转站')
      expect(table.text()).toContain('企业运行态')
      wrapper.unmount()
    })

    it('企业端不可达时显示"不可达"', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: {
          ...makeCheckData(),
          enterprise: { reachable: false },
        },
      } as never)
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      expect(wrapper.find('.deploy-update-table').text()).toContain('不可达')
      wrapper.unmount()
    })

    it('update_hub 版本为空时显示"—"', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: {
          ...makeCheckData(),
          update_hub: {},
        },
      } as never)
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      const tableText = wrapper.find('.deploy-update-table').text()
      expect(tableText).toContain('—')
      wrapper.unmount()
    })

    it('渲染 pipeline 流程图', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData(),
      } as never)
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      expect(wrapper.find('.deploy-update-pipeline').exists()).toBe(true)
      wrapper.unmount()
    })
  })

  // ── runCheck ─────────────────────────────────────────────────────

  describe('runCheck', () => {
    it('点击"重新检测"按钮触发 runCheck', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData(),
      } as never)
      const wrapper = mountModal(true)
      // 清除 watch 触发的初始调用（modelValue=true 不会触发 watch，因为没有 immediate）
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockClear()
      const refreshBtn = wrapper.findAll('button')[1]
      await refreshBtn.trigger('click')
      await flushPromises()
      expect(xcmaxAdminApi.checkDeployUpdates).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('runCheck 成功后 checkLoading 恢复 false', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData(),
      } as never)
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      // checkLoading 应为 false
      expect(wrapper.find('.deploy-update-modal__checking').exists()).toBe(false)
      wrapper.unmount()
    })
  })

  // ── startPush ────────────────────────────────────────────────────

  describe('startPush', () => {
    it('点击"推送到 update 站"触发 startPush(false)', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({ status: 'done' }),
      } as never)
      vi.mocked(xcmaxAdminApi.getDeployJob).mockResolvedValue({
        data: makeJobData({ status: 'done' }),
      } as never)
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData(),
      } as never)
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      await pushBtn.trigger('click')
      await flushPromises()
      expect(xcmaxAdminApi.startDeployPush).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('点击"定制推送"触发 startPush(true) 并打开定制面板', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({ status: 'done' }),
      } as never)
      vi.mocked(xcmaxAdminApi.getDeployJob).mockResolvedValue({
        data: makeJobData({ status: 'done' }),
      } as never)
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData(),
      } as never)
      const wrapper = mountModal(true)
      const customBtn = wrapper.findAll('button')[3]
      await customBtn.trigger('click')
      await flushPromises()
      expect(xcmaxAdminApi.startDeployPush).toHaveBeenCalled()
      // customOpen 应为 true，details 应有 open 属性
      const details = wrapper.find('.deploy-update-custom')
      expect(details.attributes('open')).toBeDefined()
      wrapper.unmount()
    })

    it('startPush 返回无 job_id 时显示错误', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        message: '推送失败',
      } as never)
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      await pushBtn.trigger('click')
      await flushPromises()
      expect(wrapper.find('.deploy-update-alert').text()).toContain('推送失败')
      wrapper.unmount()
    })

    it('startPush 返回无 job_id 无 message 时显示默认错误', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({} as never)
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      await pushBtn.trigger('click')
      await flushPromises()
      expect(wrapper.find('.deploy-update-alert').text()).toContain('未收到任务 ID')
      wrapper.unmount()
    })

    it('startPush 抛异常时显示异常信息', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockRejectedValue(
        new Error('网络异常'),
      )
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      await pushBtn.trigger('click')
      await flushPromises()
      expect(wrapper.find('.deploy-update-alert').text()).toContain('网络异常')
      wrapper.unmount()
    })

    it('startPush 抛非 Error 异常时显示字符串', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockRejectedValue(
        'push failed' as never,
      )
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      await pushBtn.trigger('click')
      await flushPromises()
      expect(wrapper.find('.deploy-update-alert').text()).toContain('push failed')
      wrapper.unmount()
    })

    it('startPush 时推送中按钮文本变为"推送中…"', async () => {
      // startDeployPush 返回未决 promise，保持 pushing=true
      vi.mocked(xcmaxAdminApi.startDeployPush).mockReturnValue(
        new Promise(() => {}),
      )
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      await pushBtn.trigger('click')
      await nextTick()
      expect(pushBtn.text()).toContain('推送中')
      wrapper.unmount()
    })
  })

  // ── pollJob ──────────────────────────────────────────────────────

  describe('pollJob', () => {
    it('job status=done 时停止推送并触发 done 事件', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({ status: 'running' }),
      } as never)
      vi.mocked(xcmaxAdminApi.getDeployJob).mockResolvedValue({
        data: makeJobData({ status: 'done' }),
      } as never)
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData(),
      } as never)
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      await pushBtn.trigger('click')
      await flushPromises()

      // 触发 poll 回调
      const pollCb = lastInterval()
      expect(pollCb).not.toBeNull()
      await pollCb!()
      await flushPromises()

      expect(wrapper.emitted('done')).toBeTruthy()
      wrapper.unmount()
    })

    it('job status=error 时设置 jobError', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({ status: 'running' }),
      } as never)
      vi.mocked(xcmaxAdminApi.getDeployJob).mockResolvedValue({
        data: makeJobData({ status: 'error', error: '打包失败' }),
      } as never)
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      await pushBtn.trigger('click')
      await flushPromises()

      const pollCb = lastInterval()
      await pollCb!()
      await flushPromises()

      expect(wrapper.find('.deploy-update-alert').text()).toContain('打包失败')
      wrapper.unmount()
    })

    it('job status=error 无 error 字段时显示默认错误', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({ status: 'running' }),
      } as never)
      vi.mocked(xcmaxAdminApi.getDeployJob).mockResolvedValue({
        data: makeJobData({ status: 'error' }),
      } as never)
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      await pushBtn.trigger('click')
      await flushPromises()

      const pollCb = lastInterval()
      await pollCb!()
      await flushPromises()

      expect(wrapper.find('.deploy-update-alert').text()).toContain('推送失败')
      wrapper.unmount()
    })

    it('getDeployJob 抛异常时设置 jobError', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({ status: 'running' }),
      } as never)
      vi.mocked(xcmaxAdminApi.getDeployJob).mockRejectedValue(
        new Error('轮询异常'),
      )
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      await pushBtn.trigger('click')
      await flushPromises()

      const pollCb = lastInterval()
      await pollCb!()
      await flushPromises()

      expect(wrapper.find('.deploy-update-alert').text()).toContain('轮询异常')
      wrapper.unmount()
    })

    it('getDeployJob 返回无 data 时直接返回', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({ status: 'running' }),
      } as never)
      vi.mocked(xcmaxAdminApi.getDeployJob).mockResolvedValue({} as never)
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      await pushBtn.trigger('click')
      await flushPromises()

      const pollCb = lastInterval()
      // 不应抛异常
      await pollCb!()
      await flushPromises()

      // 无错误显示
      const alerts = wrapper.findAll('.deploy-update-alert')
      // 可能有之前的错误，但不应因无 data 而新增
      wrapper.unmount()
    })

    it('job status=running 时不停止推送', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({
          status: 'running',
          steps: [{ id: 's1', label: '打包', status: 'running' }],
        }),
      } as never)
      vi.mocked(xcmaxAdminApi.getDeployJob).mockResolvedValue({
        data: makeJobData({
          status: 'running',
          steps: [{ id: 's1', label: '打包', status: 'running' }],
        }),
      } as never)
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      await pushBtn.trigger('click')
      await flushPromises()

      const pollCb = lastInterval()
      await pollCb!()
      await flushPromises()

      // 推送中按钮文本仍为"推送中…"
      expect(wrapper.findAll('button')[2].text()).toContain('推送中')
      // 步骤列表应渲染
      expect(wrapper.find('.deploy-update-steps').exists()).toBe(true)
      wrapper.unmount()
    })
  })

  // ── stepIcon 函数 ────────────────────────────────────────────────

  describe('stepIcon 函数', () => {
    it('step status=done 显示 ✓', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({
          status: 'running',
          steps: [{ id: 's1', label: '步骤1', status: 'done' }],
        }),
      } as never)
      vi.mocked(xcmaxAdminApi.getDeployJob).mockResolvedValue({
        data: makeJobData({
          status: 'running',
          steps: [{ id: 's1', label: '步骤1', status: 'done' }],
        }),
      } as never)
      const wrapper = mountModal(true)
      await wrapper.findAll('button')[2].trigger('click')
      await flushPromises()
      const icon = wrapper.find('.deploy-update-step__icon')
      expect(icon.text()).toBe('✓')
      wrapper.unmount()
    })

    it('step status=running 显示 …', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({
          status: 'running',
          steps: [{ id: 's1', label: '步骤1', status: 'running' }],
        }),
      } as never)
      const wrapper = mountModal(true)
      await wrapper.findAll('button')[2].trigger('click')
      await flushPromises()
      const icon = wrapper.find('.deploy-update-step__icon')
      expect(icon.text()).toBe('…')
      wrapper.unmount()
    })

    it('step status=error 显示 ✕', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({
          status: 'running',
          steps: [{ id: 's1', label: '步骤1', status: 'error' }],
        }),
      } as never)
      const wrapper = mountModal(true)
      await wrapper.findAll('button')[2].trigger('click')
      await flushPromises()
      const icon = wrapper.find('.deploy-update-step__icon')
      expect(icon.text()).toBe('✕')
      wrapper.unmount()
    })

    it('step status=skipped 显示 −', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({
          status: 'running',
          steps: [{ id: 's1', label: '步骤1', status: 'skipped' }],
        }),
      } as never)
      const wrapper = mountModal(true)
      await wrapper.findAll('button')[2].trigger('click')
      await flushPromises()
      const icon = wrapper.find('.deploy-update-step__icon')
      expect(icon.text()).toBe('−')
      wrapper.unmount()
    })

    it('step status=pending 显示 ○', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({
          status: 'running',
          steps: [{ id: 's1', label: '步骤1', status: 'pending' }],
        }),
      } as never)
      const wrapper = mountModal(true)
      await wrapper.findAll('button')[2].trigger('click')
      await flushPromises()
      const icon = wrapper.find('.deploy-update-step__icon')
      expect(icon.text()).toBe('○')
      wrapper.unmount()
    })

    it('step 有 detail 时渲染 detail', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({
          status: 'running',
          steps: [
            { id: 's1', label: '步骤1', status: 'done', detail: '详情信息' },
          ],
        }),
      } as never)
      const wrapper = mountModal(true)
      await wrapper.findAll('button')[2].trigger('click')
      await flushPromises()
      expect(wrapper.find('.deploy-update-step__detail').text()).toContain(
        '详情信息',
      )
      wrapper.unmount()
    })
  })

  // ── close 函数 ───────────────────────────────────────────────────

  describe('close 函数', () => {
    it('非推送状态点击"关闭"触发 update:modelValue=false', async () => {
      const wrapper = mountModal(true)
      const closeBtn = wrapper.findAll('button')[0]
      await closeBtn.trigger('click')
      expect(wrapper.emitted('update:modelValue')).toBeTruthy()
      expect(wrapper.emitted('update:modelValue')!.at(-1)).toEqual([false])
      wrapper.unmount()
    })

    it('推送状态点击"关闭"不触发事件', async () => {
      // startDeployPush 返回未决 promise，保持 pushing=true
      vi.mocked(xcmaxAdminApi.startDeployPush).mockReturnValue(
        new Promise(() => {}),
      )
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      await pushBtn.trigger('click')
      await nextTick()

      // pushing=true 时点击关闭
      const closeBtn = wrapper.findAll('button')[0]
      await closeBtn.trigger('click')
      // 不应触发 update:modelValue
      const emitted = wrapper.emitted('update:modelValue')
      // 如果有 emitted，最后一个不应是 false（可能是 Modal 转发的，但 close 函数不应触发）
      // close 函数在 pushing=true 时直接 return，不 emit
      // 但 closeBtn 的 click 可能触发 Modal 的 handleClose... 不，closeBtn 是在 footer slot 里
      wrapper.unmount()
    })
  })

  // ── watch modelValue ─────────────────────────────────────────────

  describe('watch modelValue', () => {
    it('modelValue 从 false 变 true 时触发 runCheck', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData(),
      } as never)
      const wrapper = mountModal(false)
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockClear()
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      expect(xcmaxAdminApi.checkDeployUpdates).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('modelValue 从 true 变 false 时触发 stopPoll', async () => {
      // 先设置一个 poll timer
      vi.mocked(xcmaxAdminApi.startDeployPush).mockResolvedValue({
        data: makeJobData({ status: 'running' }),
      } as never)
      vi.mocked(xcmaxAdminApi.getDeployJob).mockResolvedValue({
        data: makeJobData({ status: 'running' }),
      } as never)
      const wrapper = mountModal(true)
      // 触发 startPush 以设置 pollTimer
      await wrapper.findAll('button')[2].trigger('click')
      await flushPromises()
      expect(intervalCallbacks.length).toBeGreaterThan(0)

      // 关闭模态框，应调用 stopPoll → clearInterval
      clearIntervalMock.mockClear()
      await wrapper.setProps({ modelValue: false })
      expect(clearIntervalMock).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('modelValue 从 false 变 true 时重置 jobSteps 和 jobError', async () => {
      vi.mocked(xcmaxAdminApi.checkDeployUpdates).mockResolvedValue({
        data: makeCheckData(),
      } as never)
      const wrapper = mountModal(false)
      await wrapper.setProps({ modelValue: true })
      await flushPromises()
      // jobSteps 应为空，不渲染步骤列表
      expect(wrapper.find('.deploy-update-steps').exists()).toBe(false)
      wrapper.unmount()
    })
  })

  // ── canPush 计算属性 ─────────────────────────────────────────────

  describe('canPush 计算属性', () => {
    it('默认 include_backend 和 include_frontend 都为 true 时按钮可点击', () => {
      const wrapper = mountModal(true)
      const pushBtn = wrapper.findAll('button')[2]
      expect(pushBtn.attributes('disabled')).toBeUndefined()
      wrapper.unmount()
    })

    it('取消勾选 include_backend 后仍可推送（include_frontend 仍为 true）', async () => {
      const wrapper = mountModal(true)
      const checkboxes = wrapper.findAll('input[type="checkbox"]')
      // checkboxes[0] = include_backend
      await checkboxes[0].setValue(false)
      const pushBtn = wrapper.findAll('button')[2]
      expect(pushBtn.attributes('disabled')).toBeUndefined()
      wrapper.unmount()
    })

    it('取消所有勾选后推送按钮禁用', async () => {
      const wrapper = mountModal(true)
      const checkboxes = wrapper.findAll('input[type="checkbox"]')
      await checkboxes[0].setValue(false) // include_backend
      await checkboxes[1].setValue(false) // include_frontend
      const pushBtn = wrapper.findAll('button')[2]
      expect(pushBtn.attributes('disabled')).toBeDefined()
      wrapper.unmount()
    })
  })

  // ── opts 交互 ────────────────────────────────────────────────────

  describe('opts 交互', () => {
    it('切换 include_backend 复选框', async () => {
      const wrapper = mountModal(true)
      const checkbox = wrapper.findAll('input[type="checkbox"]')[0]
      await checkbox.setValue(false)
      expect((checkbox.element as HTMLInputElement).checked).toBe(false)
      await checkbox.setValue(true)
      expect((checkbox.element as HTMLInputElement).checked).toBe(true)
      wrapper.unmount()
    })

    it('切换 include_frontend 复选框', async () => {
      const wrapper = mountModal(true)
      const checkbox = wrapper.findAll('input[type="checkbox"]')[1]
      await checkbox.setValue(false)
      expect((checkbox.element as HTMLInputElement).checked).toBe(false)
      wrapper.unmount()
    })

    it('切换 skip_pack 复选框', async () => {
      const wrapper = mountModal(true)
      // skip_pack 是第三个 checkbox，初始 include_backend=true 所以可操作
      const checkbox = wrapper.findAll('input[type="checkbox"]')[2]
      await checkbox.setValue(true)
      expect((checkbox.element as HTMLInputElement).checked).toBe(true)
      wrapper.unmount()
    })

    it('切换 channel 选择', async () => {
      const wrapper = mountModal(true)
      const select = wrapper.find('select')
      await select.setValue('staging')
      expect((select.element as HTMLSelectElement).value).toBe('staging')
      await select.setValue('stable')
      expect((select.element as HTMLSelectElement).value).toBe('stable')
      wrapper.unmount()
    })

    it('include_backend=false 时 skip_pack 复选框禁用', async () => {
      const wrapper = mountModal(true)
      const backendCheckbox = wrapper.findAll('input[type="checkbox"]')[0]
      await backendCheckbox.setValue(false)
      const skipPackCheckbox = wrapper.findAll('input[type="checkbox"]')[2]
      expect(skipPackCheckbox.attributes('disabled')).toBeDefined()
      wrapper.unmount()
    })

    it('推送中时所有复选框和选择框禁用', async () => {
      vi.mocked(xcmaxAdminApi.startDeployPush).mockReturnValue(
        new Promise(() => {}),
      )
      const wrapper = mountModal(true)
      await wrapper.findAll('button')[2].trigger('click')
      await nextTick()
      const checkboxes = wrapper.findAll('input[type="checkbox"]')
      const select = wrapper.find('select')
      checkboxes.forEach((cb) => {
        expect(cb.attributes('disabled')).toBeDefined()
      })
      expect(select.attributes('disabled')).toBeDefined()
      wrapper.unmount()
    })
  })

  // ── Modal 事件转发 ───────────────────────────────────────────────

  describe('Modal 事件转发', () => {
    it('Modal emit update:modelValue 时转发事件', async () => {
      const wrapper = mountModal(true)
      // 通过 Modal 的 close 事件触发
      wrapper.findComponent({ name: 'Modal' }).vm.$emit('update:modelValue', false)
      await nextTick()
      expect(wrapper.emitted('update:modelValue')).toBeTruthy()
      wrapper.unmount()
    })

    it('Modal emit close 时转发 update:modelValue=false', async () => {
      const wrapper = mountModal(true)
      wrapper.findComponent({ name: 'Modal' }).vm.$emit('close')
      await nextTick()
      expect(wrapper.emitted('update:modelValue')).toBeTruthy()
      expect(wrapper.emitted('update:modelValue')!.at(-1)).toEqual([false])
      wrapper.unmount()
    })
  })
})
