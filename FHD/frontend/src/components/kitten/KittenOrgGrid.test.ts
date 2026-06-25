import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import KittenOrgGrid from './KittenOrgGrid.vue'

const sampleCards = [
  { key: 'ingest', title: '采集', desc: '数据采集' },
  { key: 'clean', title: '清洗', desc: '数据清洗' },
  { key: 'analyze', title: '分析', desc: '数据分析' },
  { key: 'output', title: '输出', desc: '结果输出' },
]

describe('KittenOrgGrid', () => {
  it('renders section with aria-label', () => {
    const wrapper = mount(KittenOrgGrid, { props: { cards: sampleCards } })
    expect(wrapper.find('section.kitten-org').exists()).toBe(true)
    expect(wrapper.find('section.kitten-org').attributes('aria-label')).toBe('职能模块')
  })

  it('renders the title', () => {
    const wrapper = mount(KittenOrgGrid, { props: { cards: sampleCards } })
    expect(wrapper.find('.kitten-org-title').text()).toBe('工作台职能')
  })

  it('renders no cards when cards prop is empty', () => {
    const wrapper = mount(KittenOrgGrid, { props: { cards: [] } })
    expect(wrapper.findAll('.kitten-org-card')).toHaveLength(0)
  })

  it('renders all provided cards with title and desc', () => {
    const wrapper = mount(KittenOrgGrid, { props: { cards: sampleCards } })
    const cards = wrapper.findAll('.kitten-org-card')
    expect(cards).toHaveLength(4)
    expect(cards[0].find('.kitten-org-card-title').text()).toBe('采集')
    expect(cards[0].find('.kitten-org-card-desc').text()).toBe('数据采集')
  })

  it('marks card as active when key matches activeLayerKey', () => {
    const wrapper = mount(KittenOrgGrid, {
      props: { cards: sampleCards, activeLayerKey: 'clean' },
    })
    const cards = wrapper.findAll('.kitten-org-card')
    expect(cards[1].classes()).toContain('active')
    expect(cards[0].classes()).not.toContain('active')
  })

  it('uses default activeLayerKey=ingest', () => {
    const wrapper = mount(KittenOrgGrid, { props: { cards: sampleCards } })
    const cards = wrapper.findAll('.kitten-org-card')
    expect(cards[0].classes()).toContain('active')
  })

  it('updates active card when activeLayerKey changes', async () => {
    const wrapper = mount(KittenOrgGrid, {
      props: { cards: sampleCards, activeLayerKey: 'ingest' },
    })
    expect(wrapper.findAll('.kitten-org-card')[0].classes()).toContain('active')
    await wrapper.setProps({ activeLayerKey: 'analyze' })
    expect(wrapper.findAll('.kitten-org-card')[0].classes()).not.toContain('active')
    expect(wrapper.findAll('.kitten-org-card')[2].classes()).toContain('active')
  })

  it('no card is active when activeLayerKey does not match any card', () => {
    const wrapper = mount(KittenOrgGrid, {
      props: { cards: sampleCards, activeLayerKey: 'nonexistent' },
    })
    const cards = wrapper.findAll('.kitten-org-card')
    cards.forEach((c) => expect(c.classes()).not.toContain('active'))
  })
})
