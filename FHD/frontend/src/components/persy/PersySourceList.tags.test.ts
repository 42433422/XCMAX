import { afterEach, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import PersySourceList from './PersySourceList.vue'
let wrapper: VueWrapper | undefined
afterEach(() => wrapper?.unmount())
it('filters by normalized tags and restores all sources when toggled off', async () => {
  const documents = [
    { document_id: 'a', source: '财务.xlsx', metadata: { tags: [' 财务 ', '报表'] } },
    { document_id: 'b', source: '说明.pdf', metadata: { tags: '说明' } },
  ]
  wrapper = mount(PersySourceList, { props: { documents, deletingDocumentId: '' }, global: { stubs: { FileTypeIcon: true } } })
  expect(wrapper.findAll('.source-row')).toHaveLength(2)
  const tag = wrapper.findAll('.tag-filter__item').find(item => item.text() === '财务')!
  await tag.trigger('click')
  expect(wrapper.findAll('.source-row')).toHaveLength(1)
  expect(wrapper.get('.source-total').text()).toBe('1 / 2 个来源')
  await wrapper.get('.source-row__select').trigger('click')
  expect(wrapper.emitted('select')).toEqual([[documents[0]]])
  await tag.trigger('click')
  expect(wrapper.findAll('.source-row')).toHaveLength(2)
})
it('offers a recovery action if an active tag disappears after the sources refresh', async () => {
  wrapper = mount(PersySourceList, { props: { documents: [{ document_id: 'a', source: 'old.pdf', metadata: { tags: ['旧'] } }], deletingDocumentId: '' }, global: { stubs: { FileTypeIcon: true } } })
  await wrapper.get('.tag-filter__item').trigger('click')
  await wrapper.setProps({ documents: [{ document_id: 'b', source: 'new.pdf' }] })
  expect(wrapper.get('.view-empty').text()).toContain('该标签下没有资料')
  await wrapper.get('.view-empty button').trigger('click')
  expect(wrapper.get('.source-row').text()).toContain('new.pdf')
})
