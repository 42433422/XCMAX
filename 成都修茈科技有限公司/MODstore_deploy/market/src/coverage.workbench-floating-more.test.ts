import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'

import AgentMarket from './components/workbench/AgentMarket.vue'
import MessageActions from './components/workbench/MessageActions.vue'
import SkillToolbar from './components/workbench/SkillToolbar.vue'
import AgentActionPreview from './components/floating-agent/AgentActionPreview.vue'
import AgentMessageBubble from './components/floating-agent/AgentMessageBubble.vue'
import AgentStatusBar from './components/floating-agent/AgentStatusBar.vue'
import AgentSuggestionToast from './components/floating-agent/AgentSuggestionToast.vue'
import CorpWelcomeBoard from './components/floating-agent/CorpWelcomeBoard.vue'
import { ALL_SKILLS } from './utils/chatSkills'
import type { AgentBot } from './utils/agentBots'

const componentMocks = vi.hoisted(() => ({
  routerPush: vi.fn(),
  openPanel: vi.fn(),
  openContactIntakeModal: vi.fn(),
  contactIntakeFillCompleted: { value: false },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: componentMocks.routerPush }),
}))

vi.mock('./stores/agent', () => ({
  useAgentStore: () => ({ openPanel: componentMocks.openPanel }),
}))

vi.mock('./corp-butler/useContactIntakeModal', () => ({
  contactIntakeFillCompleted: componentMocks.contactIntakeFillCompleted,
  openContactIntakeModal: componentMocks.openContactIntakeModal,
}))

const bots: AgentBot[] = [
  {
    id: 'official_writer',
    name: '脚本助手',
    desc: '生成短视频脚本',
    icon: 'W',
    category: '内容',
    tags: ['脚本', '短视频'],
    uses: 12,
    builtin: true,
  },
  {
    id: 'my_sales',
    name: '我的销售',
    desc: '跟进客户',
    icon: 'S',
    category: '销售',
    tags: ['客户'],
    uses: 3,
    mine: true,
    favorite: true,
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  componentMocks.contactIntakeFillCompleted.value = false
})

afterEach(() => {
  vi.useRealTimers()
})

describe('workbench and floating agent extra component coverage', () => {
  it('filters AgentMarket bots and emits bot operations', async () => {
    const wrapper = mount(AgentMarket, {
      props: { open: true, bots },
    })

    expect(wrapper.text()).toContain('全部 2')
    await wrapper.find('input[type="search"]').setValue('销售')
    expect(wrapper.text()).toContain('我的销售')
    expect(wrapper.text()).not.toContain('脚本助手')

    await wrapper.findAll('.am-cat').find((btn) => btn.text().startsWith('收藏'))!.trigger('click')
    expect(wrapper.text()).toContain('我的销售')

    await wrapper.findAll('button').find((btn) => btn.text().includes('开始对话'))!.trigger('click')
    await wrapper.findAll('button').find((btn) => btn.text().includes('删除'))!.trigger('click')
    await wrapper.findAll('button').find((btn) => btn.text().includes('已收藏'))!.trigger('click')
    expect(wrapper.emitted('start')?.[0]?.[0]).toMatchObject({ id: 'my_sales' })
    expect(wrapper.emitted('remove')?.[0]?.[0]).toMatchObject({ id: 'my_sales' })
    expect(wrapper.emitted('favorite')?.[0]?.[0]).toMatchObject({ id: 'my_sales' })
  })

  it('creates an AgentMarket custom bot and resets panel state when closed', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(123456789)
    const wrapper = mount(AgentMarket, {
      props: { open: true, bots },
    })

    await wrapper.findAll('button').find((btn) => btn.text().includes('创建智能体'))!.trigger('click')
    await wrapper.find('input[placeholder="例如：抖音脚本搭子"]').setValue('运营搭子')
    await wrapper.find('input[placeholder="按口播节奏写脚本，附拍摄分镜"]').setValue('')
    await wrapper.find('textarea').setValue('你负责输出运营建议和下一步动作')
    await wrapper.find('input[placeholder="嗨～告诉我你想做什么主题的视频？"]').setValue('')
    await wrapper.find('input[placeholder="抖音, 脚本, 口播"]').setValue('运营，增长, 复盘, 超出')
    await wrapper.findAll('button').find((btn) => btn.text().includes('保存到'))!.trigger('click')

    const created = wrapper.emitted('create')?.[0]?.[0] as AgentBot
    expect(created).toMatchObject({
      id: 'mybot_21i3v9',
      name: '运营搭子',
      desc: '运营搭子 —— 我的智能体',
      opener: '需要我做什么？',
      tags: ['运营', '增长', '复盘'],
      favorite: true,
      mine: true,
    })

    await wrapper.find('input[type="search"]').setValue('脚本')
    await wrapper.setProps({ open: false })
    await wrapper.setProps({ open: true })
    expect((wrapper.find('input[type="search"]').element as HTMLInputElement).value).toBe('')
  })

  it('toggles SkillToolbar skills on and off', async () => {
    const firstSkillId = ALL_SKILLS[0].id
    const wrapper = mount(SkillToolbar, { props: { active: [] } })

    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('update:active')?.[0]?.[0]).toEqual([firstSkillId])

    await wrapper.setProps({ active: [firstSkillId] })
    expect(wrapper.text()).toContain('已开启 1 项')
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('update:active')?.[1]?.[0]).toEqual([])
  })

  it('handles MessageActions copy, speech, regeneration and feedback', async () => {
    vi.useFakeTimers()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const wrapper = mount(MessageActions, {
      props: {
        role: 'assistant',
        content: '回复内容',
        canRegenerate: true,
        speaking: false,
        feedback: 'up',
      },
    })

    await wrapper.findAll('button').find((btn) => btn.text() === '朗读')!.trigger('click')
    await wrapper.find('[aria-label="复制"]').trigger('click')
    await nextTick()
    expect(writeText).toHaveBeenCalledWith('回复内容')
    expect(wrapper.text()).toContain('已复制')
    vi.advanceTimersByTime(1500)
    await nextTick()
    expect(wrapper.text()).toContain('复制')

    await wrapper.find('[aria-label="重新生成"]').trigger('click')
    await wrapper.findAll('button').find((btn) => btn.text() === '👍')!.trigger('click')
    await wrapper.findAll('button').find((btn) => btn.text() === '👎')!.trigger('click')
    expect(wrapper.emitted('speak')).toHaveLength(1)
    expect(wrapper.emitted('regenerate')).toHaveLength(1)
    expect(wrapper.emitted('feedback')?.map((row) => row[0])).toEqual([null, 'down'])
  })

  it('handles MessageActions user edit and clipboard failure paths', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    })
    const wrapper = mount(MessageActions, {
      props: { role: 'user', content: '原始问题' },
    })

    await wrapper.find('[aria-label="复制"]').trigger('click')
    await wrapper.findAll('button').find((btn) => btn.text() === '编辑')!.trigger('click')
    expect(wrapper.emitted('edit')).toHaveLength(1)
    expect(wrapper.text()).toContain('复制')
  })

  it('renders AgentMessageBubble role variants and escaped markdown', () => {
    const base = { id: 'm1', timestamp: new Date('2026-06-18T10:05:00').getTime() }
    const assistant = mount(AgentMessageBubble, {
      props: { msg: { ...base, role: 'assistant', content: '**重点**\n<script>' } },
    })
    expect(assistant.html()).toContain('<strong>重点</strong>')
    expect(assistant.html()).toContain('&lt;script&gt;')
    expect(assistant.text()).toContain('10:05')

    expect(mount(AgentMessageBubble, {
      props: { msg: { ...base, role: 'assistant', content: '', isLoading: true } },
    }).find('.bubble-dots').exists()).toBe(true)
    expect(mount(AgentMessageBubble, {
      props: { msg: { ...base, role: 'tool_call', content: '', toolCall: { name: 'search', args: { q: '客户', limit: 2 } } } },
    }).text()).toContain('search: q=客户, limit=2')
    expect(mount(AgentMessageBubble, {
      props: { msg: { ...base, role: 'action_preview', content: '', actionPreview: { id: 'a1', label: '删除资料', risk: 'high' } } },
    }).text()).toContain('高风险')
    expect(mount(AgentMessageBubble, {
      props: { msg: { ...base, role: 'action_preview', content: '', actionPreview: { id: 'a2', label: '同步客户', risk: 'medium' } } },
    }).text()).toContain('中风险')
    expect(mount(AgentMessageBubble, {
      props: { msg: { ...base, role: 'user', content: '用户问题' } },
    }).text()).toContain('用户问题')
  })

  it('renders AgentStatusBar labels and stop controls', async () => {
    expect(mount(AgentStatusBar, { props: { mode: 'idle' } }).html()).toBe('<!--v-if-->')

    const listening = mount(AgentStatusBar, { props: { mode: 'listening' } })
    expect(listening.text()).toContain('我在听')
    await listening.find('button').trigger('click')
    expect(listening.emitted('stop')).toHaveLength(1)

    expect(mount(AgentStatusBar, { props: { mode: 'thinking' } }).text()).toContain('AI 思考中')
    expect(mount(AgentStatusBar, { props: { mode: 'operating' } }).text()).toContain('正在操作页面')
    expect(mount(AgentStatusBar, { props: { mode: 'awaiting_confirm' } }).find('button').exists()).toBe(false)
    expect(mount(AgentStatusBar, { props: { mode: 'speaking' } }).text()).toContain('AI 正在朗读')
    expect(mount(AgentStatusBar, { props: { mode: 'error' } }).text()).toContain('出现错误')
  })

  it('emits AgentActionPreview confirmation events for risk levels', async () => {
    const high = mount(AgentActionPreview, {
      props: { action: { id: 'danger', label: '删除全部', risk: 'high' } },
    })
    expect(high.text()).toContain('高风险')
    expect(high.text()).toContain('无法撤销')
    await high.findAll('button').find((btn) => btn.text() === '取消')!.trigger('click')
    await high.findAll('button').find((btn) => btn.text().includes('确认执行'))!.trigger('click')
    expect(high.emitted('cancel')).toHaveLength(1)
    expect(high.emitted('confirm')).toHaveLength(1)

    expect(mount(AgentActionPreview, {
      props: { action: { id: 'medium', label: '同步客户', risk: 'medium' } },
    }).text()).toContain('中风险')
    expect(mount(AgentActionPreview, {
      props: { action: { id: 'low', label: '读取资料', risk: 'low' } },
    }).text()).toContain('低风险')
  })

  it('routes or opens panel from AgentSuggestionToast actions', async () => {
    const routed = mount(AgentSuggestionToast, {
      props: {
        suggestion: {
          id: 's1',
          message: '去配置',
          actionLabel: '打开',
          actionRoute: 'settings',
          priority: 1,
        },
      },
    })
    await routed.findAll('button').find((btn) => btn.text() === '打开')!.trigger('click')
    expect(componentMocks.routerPush).toHaveBeenCalledWith({ name: 'settings' })
    expect(routed.emitted('dismiss')?.[0]).toEqual(['s1'])

    const panel = mount(AgentSuggestionToast, {
      props: {
        suggestion: {
          id: 's2',
          message: '继续处理',
          actionLabel: '处理',
          priority: 1,
        },
      },
    })
    await panel.findAll('button').find((btn) => btn.text() === '处理')!.trigger('click')
    expect(componentMocks.openPanel).toHaveBeenCalled()
    expect(panel.emitted('open-panel')).toHaveLength(1)
    expect(panel.emitted('dismiss')?.[0]).toEqual(['s2'])

    await panel.findAll('button').find((btn) => btn.text() === '忽略')!.trigger('click')
    expect(panel.emitted('dismiss')?.[1]).toEqual(['s2'])
    expect(mount(AgentSuggestionToast, { props: { suggestion: null } }).find('.suggestion-toast').exists()).toBe(false)
  })

  it('emits CorpWelcomeBoard tasks and opens contact intake on mobile', async () => {
    const task = { label: '咨询报价', message: '我要报价' }
    const desktop = mount(CorpWelcomeBoard, {
      props: { subtitle: '欢迎', tasks: [task], isContactPage: true },
    })
    await desktop.find('button').trigger('click')
    expect(desktop.emitted('task')?.[0]?.[0]).toEqual(task)
    expect(desktop.text()).toContain('直接描述您的场景')

    componentMocks.contactIntakeFillCompleted.value = true
    const mobile = mount(CorpWelcomeBoard, {
      props: { subtitle: '欢迎', tasks: [task], isMobileContact: true },
    })
    expect(mobile.text()).toContain('已预填')
    await mobile.find('button').trigger('click')
    expect(componentMocks.openContactIntakeModal).toHaveBeenCalled()
    expect(mobile.text()).toContain('也可在下方输入框')
  })
})
