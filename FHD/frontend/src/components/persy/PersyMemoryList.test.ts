import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { PersyMemoryRecord } from '@/api/knowledgeBase'
import PersyMemoryList from './PersyMemoryList.vue'

const pendingMemory: PersyMemoryRecord = {
  memory_id: 'm-pending',
  memory_type: 'preference',
  statement: '客户偏好周五交付',
  status: 'pending',
  scope: 'user',
  strength: 0.8,
  updated_at: '2026-08-01T10:00:00Z',
}

describe('PersyMemoryList', () => {
  it('emits selection and governance actions for a pending memory', async () => {
    const wrapper = mount(PersyMemoryList, {
      props: {
        memories: [pendingMemory],
        loading: false,
        activeCount: 0,
        pendingCount: 1,
        selectedMemoryId: '',
        mutating: false,
      },
    })

    await wrapper.get('.memory-row__main').trigger('click')
    await wrapper.get('button[aria-label="确认记忆"]').trigger('click')
    await wrapper.get('button[aria-label="忽略记忆"]').trigger('click')

    expect(wrapper.emitted('select')).toEqual([[pendingMemory]])
    expect(wrapper.emitted('confirm')).toEqual([[pendingMemory]])
    expect(wrapper.emitted('reject')).toEqual([[pendingMemory]])
  })
})
