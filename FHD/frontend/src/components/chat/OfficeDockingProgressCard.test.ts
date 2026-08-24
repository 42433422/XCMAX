import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import OfficeDockingProgressCard from './OfficeDockingProgressCard.vue'
import type { ChatOfficeDockingProgress } from '@/composables/useChatOfficeDocking'

const progress: ChatOfficeDockingProgress = {
  phase: 'reading',
  sourceLabel: '文件夹「发货单」',
  total: 17,
  completed: 6,
  currentIndex: 7,
  currentFile: '发货单/国圣化工.xlsx',
  success: 5,
  failed: 1,
  failures: [{ fileName: '发货单/损坏.xlsx', reason: '工作簿结构损坏' }],
  ignored: [{ fileName: '发货单/.DS_Store', reason: '系统或临时文件' }],
  elapsedSeconds: 82,
  percent: 35,
}

describe('OfficeDockingProgressCard', () => {
  it('shows live batch status, ignored reasons, safety boundary, and cancellation', async () => {
    const wrapper = mount(OfficeDockingProgressCard, { props: { progress } })

    expect(wrapper.text()).toContain('正在阅读文件夹「发货单」')
    expect(wrapper.text()).toContain('6/17')
    expect(wrapper.text()).toContain('第 7 个')
    expect(wrapper.text()).toContain('国圣化工.xlsx')
    expect(wrapper.text()).toContain('成功 5')
    expect(wrapper.text()).toContain('失败 1')
    expect(wrapper.text()).toContain('损坏.xlsx')
    expect(wrapper.text()).toContain('工作簿结构损坏')
    expect(wrapper.text()).toContain('跳过 1')
    expect(wrapper.text()).toContain('系统或临时文件')
    expect(wrapper.text()).toContain('不会归档模板，也不会写入数据库')
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('35')

    await wrapper.get('.office-reading-card__cancel').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })
})
