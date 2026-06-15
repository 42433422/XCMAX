import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('@/utils/appDialog', () => ({
  appConfirm: vi.fn().mockResolvedValue(true),
}))

import UserListPanel from '@/components/pro-feature-widget/UserListPanel.vue'

const sampleCustomers = [
  { id: 1, name: '张三', phone: '13800138001', email: 'zhang@test.com', company: '测试公司A' },
  { id: 2, name: '李四', phone: '13800138002', email: 'li@test.com', company: '测试公司B' },
  { id: 3, name: '王五', phone: '', email: '', company: '' },
]

function mountComponent(propsOverrides = {}) {
  return mount(UserListPanel, {
    props: {
      customers: sampleCustomers,
      ...propsOverrides,
    },
  })
}

describe('UserListPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the panel container', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.user-list-panel').exists()).toBe(true)
  })

  it('renders panel title', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.panel-title').text()).toBe('客户管理')
  })

  it('renders add customer button', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.action-btn.add').exists()).toBe(true)
    expect(wrapper.find('.action-btn.add').text()).toContain('添加客户')
  })

  it('renders export button', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.action-btn.export').exists()).toBe(true)
  })

  it('renders search input', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.search-input').exists()).toBe(true)
  })

  it('renders all customers', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.customer-item').length).toBe(3)
  })

  it('displays customer name', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('李四')
  })

  it('displays customer contact info', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('13800138001')
  })

  it('shows 无联系方式 for customer without contact', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('无联系方式')
  })

  it('shows first character of name as avatar', () => {
    const wrapper = mountComponent()
    const avatars = wrapper.findAll('.customer-avatar')
    expect(avatars[0].text()).toBe('张')
    expect(avatars[1].text()).toBe('李')
  })

  it('filters customers by search query', async () => {
    const wrapper = mountComponent()
    const input = wrapper.find('.search-input')
    await input.setValue('张')
    expect(wrapper.findAll('.customer-item').length).toBe(1)
    expect(wrapper.text()).toContain('张三')
  })

  it('filters customers by phone', async () => {
    const wrapper = mountComponent()
    const input = wrapper.find('.search-input')
    await input.setValue('13800138002')
    expect(wrapper.findAll('.customer-item').length).toBe(1)
    expect(wrapper.text()).toContain('李四')
  })

  it('filters customers by email', async () => {
    const wrapper = mountComponent()
    const input = wrapper.find('.search-input')
    await input.setValue('li@test.com')
    expect(wrapper.findAll('.customer-item').length).toBe(1)
  })

  it('filters customers by company', async () => {
    const wrapper = mountComponent()
    const input = wrapper.find('.search-input')
    await input.setValue('测试公司A')
    expect(wrapper.findAll('.customer-item').length).toBe(1)
  })

  it('shows empty state when no customers match search', async () => {
    const wrapper = mountComponent()
    const input = wrapper.find('.search-input')
    await input.setValue('不存在的客户')
    expect(wrapper.find('.empty-state').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无客户数据')
  })

  it('shows empty state when customers prop is empty', () => {
    const wrapper = mountComponent({ customers: [] })
    expect(wrapper.find('.empty-state').exists()).toBe(true)
  })

  it('selects customer on click', async () => {
    const wrapper = mountComponent()
    await wrapper.findAll('.customer-item')[0].trigger('click')
    const vm = wrapper.vm as any
    expect(vm.selectedCustomer.id).toBe(1)
  })

  it('adds selected class to selected customer', async () => {
    const wrapper = mountComponent()
    await wrapper.findAll('.customer-item')[0].trigger('click')
    expect(wrapper.findAll('.customer-item')[0].classes()).toContain('selected')
  })

  it('opens add modal on add button click', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.action-btn.add').trigger('click')
    const vm = wrapper.vm as any
    expect(vm.showEditModal).toBe(true)
    expect(vm.editingCustomer).toBeNull()
  })

  it('opens edit modal with customer data on edit click', async () => {
    const wrapper = mountComponent()
    const editBtn = wrapper.findAll('.icon-btn.edit')[0]
    await editBtn.trigger('click')
    const vm = wrapper.vm as any
    expect(vm.showEditModal).toBe(true)
    expect(vm.editingCustomer).toBeTruthy()
    expect(vm.editForm.name).toBe('张三')
  })

  it('emits delete on delete button click', async () => {
    const wrapper = mountComponent()
    const deleteBtn = wrapper.findAll('.icon-btn.delete')[0]
    await deleteBtn.trigger('click')
    // appConfirm is mocked to return true
    expect(wrapper.emitted('delete')).toBeTruthy()
  })

  it('emits export on export button click', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.action-btn.export').trigger('click')
    expect(wrapper.emitted('export')).toBeTruthy()
  })

  it('emits add when saving new customer', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.handleAdd()
    vm.editForm.name = '新客户'
    vm.editForm.phone = '13900139000'
    vm.saveCustomer()
    expect(wrapper.emitted('add')).toBeTruthy()
    expect(wrapper.emitted('add')![0][0]).toHaveProperty('name', '新客户')
  })

  it('emits edit when saving existing customer', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.handleEdit(sampleCustomers[0])
    vm.editForm.name = '张三改'
    vm.saveCustomer()
    expect(wrapper.emitted('edit')).toBeTruthy()
    expect(wrapper.emitted('edit')![0][0]).toHaveProperty('id', 1)
    expect(wrapper.emitted('edit')![0][0]).toHaveProperty('name', '张三改')
  })

  it('closes modal on cancel', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.showEditModal = true
    vm.closeModal()
    expect(vm.showEditModal).toBe(false)
    expect(vm.editingCustomer).toBeNull()
  })

  it('renders edit modal with form fields', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.showEditModal = true
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.edit-modal').exists()).toBe(true)
    expect(wrapper.find('.form-input').exists()).toBe(true)
  })

  it('renders modal header correctly for add mode', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.handleAdd()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('添加客户')
  })

  it('renders modal header correctly for edit mode', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.handleEdit(sampleCustomers[0])
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('编辑客户')
  })

  it('search is case insensitive', async () => {
    const wrapper = mountComponent()
    const input = wrapper.find('.search-input')
    await input.setValue('ZHANG')
    expect(wrapper.findAll('.customer-item').length).toBe(1)
  })
})
