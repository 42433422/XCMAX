import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { KnowledgeBaseDocument } from '@/api/knowledgeBase'
import FileTypeIcon from '@/components/common/FileTypeIcon.vue'
import PersySourceList from './PersySourceList.vue'

const documents: KnowledgeBaseDocument[] = [
  {
    document_id: 'doc-refund',
    source: '退款.md',
    parser: 'markdown',
    text_length: 120,
    chunk_count: 2,
    metadata: { tags: ['售后', '财务'] },
  },
  {
    document_id: 'doc-invoice',
    source: '发票.md',
    parser: 'markdown',
    text_length: 90,
    chunk_count: 1,
    metadata: { tags: ['财务'] },
  },
  {
    document_id: 'doc-misc',
    source: '其他.md',
    parser: 'markdown',
    text_length: 60,
    chunk_count: 1,
    metadata: {},
  },
]

function mountList(items: KnowledgeBaseDocument[] = documents) {
  return mount(PersySourceList, {
    props: { documents: items, deletingDocumentId: '' },
  })
}

describe('PersySourceList', () => {
  it('renders document tags and emits selection', async () => {
    const wrapper = mountList()

    expect(wrapper.get('.source-total').text()).toContain('3 / 3')
    expect(wrapper.findAllComponents(FileTypeIcon).map((icon) => icon.props('name')))
      .toEqual(documents.map((document) => document.source))
    expect(wrapper.findAll('.source-row__tags em').map((item) => item.text())).toEqual([
      '售后',
      '财务',
      '财务',
    ])

    await wrapper.get('.source-row__select').trigger('click')
    expect(wrapper.emitted('select')).toEqual([[documents[0]]])
  })

  it('filters by tag and clears the filter', async () => {
    const wrapper = mountList()
    const filter = wrapper.findAll('.tag-filter__item')
    const finance = filter.find((item) => item.text() === '财务')

    await finance!.trigger('click')
    expect(wrapper.findAll('.source-row')).toHaveLength(2)
    expect(wrapper.findAllComponents(FileTypeIcon).map((icon) => icon.props('name')))
      .toEqual(['退款.md', '发票.md'])
    expect(wrapper.get('.source-total').text()).toContain('2 / 3')
    expect(wrapper.get('.tag-filter__clear').exists()).toBe(true)

    await wrapper.get('.tag-filter__clear').trigger('click')
    expect(wrapper.findAll('.source-row')).toHaveLength(3)
  })

  it('shows an empty state when a tag has no documents', async () => {
    const wrapper = mountList([documents[2]])
    expect(wrapper.find('.tag-filter').exists()).toBe(false)
    expect(wrapper.findAll('.source-row')).toHaveLength(1)
  })
})
