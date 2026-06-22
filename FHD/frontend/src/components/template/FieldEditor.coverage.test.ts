import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

vi.mock('@/utils/appDialog', () => ({
  appConfirm: vi.fn().mockResolvedValue(true),
}))

import { appConfirm } from '@/utils/appDialog'
import FieldEditor from '@/components/template/FieldEditor.vue'

function makeField(overrides = {}) {
  return { label: '品名', value: '运动鞋', type: 'dynamic', ...overrides }
}

function mountComponent(propsOverrides = {}) {
  return mount(FieldEditor, {
    props: {
      fields: [makeField(), makeField({ label: '规格', value: '42码', type: 'fixed' })],
      templateType: 'excel',
      ...propsOverrides,
    },
    global: {
      stubs: {
        ExcelPreview: true,
        LabelPreview: true,
        PaneResizeHandle: true,
      },
    },
  })
}

describe('FieldEditor.coverage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    ;(appConfirm as any).mockResolvedValue(true)
  })

  it('renders field list with provided fields', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.field-item').length).toBe(2)
  })

  it('renders empty hint when no fields', () => {
    const wrapper = mountComponent({ fields: [] })
    expect(wrapper.find('.empty-fields').exists()).toBe(true)
  })

  it('renders excel preview when templateType is excel', () => {
    const wrapper = mountComponent({ templateType: 'excel' })
    expect(wrapper.findComponent({ name: 'ExcelPreview' }).exists()).toBe(true)
  })

  it('renders word preview chips when templateType is word', () => {
    const wrapper = mountComponent({ templateType: 'word' })
    expect(wrapper.find('.word-preview-box').exists()).toBe(true)
    expect(wrapper.findAll('.word-chip').length).toBe(2)
  })

  it('renders word empty hint when no fields', () => {
    const wrapper = mountComponent({ templateType: 'word', fields: [] })
    expect(wrapper.find('.word-preview-box .muted').exists()).toBe(true)
  })

  it('renders label preview when templateType is label', () => {
    const wrapper = mountComponent({ templateType: 'label' })
    expect(wrapper.findComponent({ name: 'LabelPreview' }).exists()).toBe(true)
  })

  it('selectField sets editingIndex', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).selectField(1)
    expect((wrapper.vm as any).editingIndex).toBe(1)
  })

  it('selectField via click sets active class', async () => {
    const wrapper = mountComponent()
    const items = wrapper.findAll('.field-item')
    await items[1].trigger('click')
    expect(items[1].classes()).toContain('active')
  })

  it('editField opens modal with field copy', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).editField(0)
    await nextTick()
    expect((wrapper.vm as any).editingField).toBeTruthy()
    expect((wrapper.vm as any).editingField.label).toBe('品名')
    expect(wrapper.find('.field-edit-modal').exists()).toBe(true)
  })

  it('editField via button click opens modal', async () => {
    const wrapper = mountComponent()
    const editBtn = wrapper.findAll('.btn-icon')[0]
    await editBtn.trigger('click')
    expect(wrapper.find('.field-edit-modal').exists()).toBe(true)
  })

  it('closeEditModal clears editingField', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).editField(0)
    await nextTick()
    expect(wrapper.find('.field-edit-modal').exists()).toBe(true)
    ;(wrapper.vm as any).closeEditModal()
    await nextTick()
    expect((wrapper.vm as any).editingField).toBeNull()
    expect(wrapper.find('.field-edit-modal').exists()).toBe(false)
  })

  it('closeEditModal via overlay click closes modal', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).editField(0)
    await nextTick()
    await wrapper.find('.modal-overlay').trigger('click.self')
    expect((wrapper.vm as any).editingField).toBeNull()
  })

  it('closeEditModal via close button closes modal', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).editField(0)
    await nextTick()
    await wrapper.find('.modal-close').trigger('click')
    expect((wrapper.vm as any).editingField).toBeNull()
  })

  it('closeEditModal via cancel button closes modal', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).editField(0)
    await nextTick()
    const cancelBtn = wrapper.findAll('.modal-footer .btn-secondary')[0]
    await cancelBtn.trigger('click')
    expect((wrapper.vm as any).editingField).toBeNull()
  })

  it('saveFieldEdit emits update-field and closes modal', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).editField(0)
    await nextTick()
    ;(wrapper.vm as any).editingField.label = '新品名'
    ;(wrapper.vm as any).saveFieldEdit()
    expect(wrapper.emitted('update-field')).toBeTruthy()
    const evt = wrapper.emitted('update-field')![0]
    expect(evt[0]).toBe(0)
    expect(evt[1].label).toBe('新品名')
    expect((wrapper.vm as any).editingField).toBeNull()
  })

  it('saveFieldEdit does nothing when editingIndex is null', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).editingIndex = null
    ;(wrapper.vm as any).editingField = null
    ;(wrapper.vm as any).saveFieldEdit()
    expect(wrapper.emitted('update-field')).toBeFalsy()
  })

  it('saveFieldEdit via save button click emits update-field', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).editField(0)
    await nextTick()
    const saveBtn = wrapper.find('.modal-footer .btn-primary')
    await saveBtn.trigger('click')
    expect(wrapper.emitted('update-field')).toBeTruthy()
  })

  it('toggleType switches fixed to dynamic', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).toggleType(1)
    expect(wrapper.emitted('update-field')).toBeTruthy()
    const evt = wrapper.emitted('update-field')![0]
    expect(evt[0]).toBe(1)
    expect(evt[1].type).toBe('dynamic')
  })

  it('toggleType switches dynamic to fixed', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).toggleType(0)
    const evt = wrapper.emitted('update-field')![0]
    expect(evt[1].type).toBe('fixed')
  })

  it('toggleType via badge click emits update-field', async () => {
    const wrapper = mountComponent()
    const badge = wrapper.find('.type-badge')
    await badge.trigger('click')
    expect(wrapper.emitted('update-field')).toBeTruthy()
  })

  it('deleteField emits delete-field when confirmed', async () => {
    const wrapper = mountComponent()
    await (wrapper.vm as any).deleteField(0)
    expect(appConfirm).toHaveBeenCalled()
    expect(wrapper.emitted('delete-field')).toBeTruthy()
    expect(wrapper.emitted('delete-field')![0][0]).toBe(0)
  })

  it('deleteField does not emit when not confirmed', async () => {
    ;(appConfirm as any).mockResolvedValue(false)
    const wrapper = mountComponent()
    await (wrapper.vm as any).deleteField(0)
    expect(wrapper.emitted('delete-field')).toBeFalsy()
  })

  it('deleteField clears editingIndex when deleting active field', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).selectField(0)
    await (wrapper.vm as any).deleteField(0)
    expect((wrapper.vm as any).editingIndex).toBeNull()
  })

  it('deleteField keeps editingIndex when deleting different field', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).selectField(1)
    await (wrapper.vm as any).deleteField(0)
    expect((wrapper.vm as any).editingIndex).toBe(1)
  })

  it('deleteField via trash button click emits delete-field', async () => {
    const wrapper = mountComponent()
    const trashBtn = wrapper.findAll('.btn-icon.btn-danger')[0]
    await trashBtn.trigger('click')
    expect(wrapper.emitted('delete-field')).toBeTruthy()
  })

  it('addField emits add-field with default new field', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).addField()
    expect(wrapper.emitted('add-field')).toBeTruthy()
    const evt = wrapper.emitted('add-field')![0]
    expect(evt[0]).toEqual({ label: '新字段', value: '示例值', type: 'dynamic' })
  })

  it('addField via button click emits add-field', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.add-field-actions .btn').trigger('click')
    expect(wrapper.emitted('add-field')).toBeTruthy()
  })

  it('onFieldChange emits fields-change with copy', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).onFieldChange()
    expect(wrapper.emitted('fields-change')).toBeTruthy()
    const evt = wrapper.emitted('fields-change')![0]
    expect(evt[0]).toHaveLength(2)
    expect(evt[0]).not.toBe((wrapper.vm as any).fields)
  })

  it('onFieldChange via input change emits fields-change', async () => {
    const wrapper = mountComponent()
    const input = wrapper.find('input[type="text"]')
    await input.trigger('change')
    expect(wrapper.emitted('fields-change')).toBeTruthy()
  })

  it('getFields returns a copy of fields', () => {
    const wrapper = mountComponent()
    const result = (wrapper.vm as any).getFields()
    expect(result).toHaveLength(2)
    expect(result).not.toBe((wrapper.vm as any).fields)
  })

  it('isEditorPaneResizable is true by default (matchMedia returns false)', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).isEditorPaneResizable).toBe(true)
  })

  it('editorPaneStyle is an object with css var', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).editorPaneStyle).toBeTruthy()
  })

  it('resetEditorPaneWidth is exposed and callable', () => {
    const wrapper = mountComponent()
    expect(typeof (wrapper.vm as any).resetEditorPaneWidth).toBe('function')
    expect(() => (wrapper.vm as any).resetEditorPaneWidth()).not.toThrow()
  })

  it('onEditorPaneResizeStart is exposed and callable', () => {
    const wrapper = mountComponent()
    expect(typeof (wrapper.vm as any).onEditorPaneResizeStart).toBe('function')
  })

  it('renders PaneResizeHandle when resizable', () => {
    const wrapper = mountComponent()
    expect(wrapper.findComponent({ name: 'PaneResizeHandle' }).exists()).toBe(true)
  })

  it('unmounts without errors (covers onBeforeUnmount)', async () => {
    const wrapper = mountComponent()
    expect(() => wrapper.unmount()).not.toThrow()
  })

  it('handles addEventListener fallback (addListener) when addEventListener missing', async () => {
    const addListener = vi.fn()
    const removeListener = vi.fn()
    ;(window.matchMedia as any).mockImplementationOnce((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener,
      removeListener,
      addEventListener: undefined,
      removeEventListener: undefined,
      dispatchEvent: vi.fn(() => false),
    }))
    const wrapper = mountComponent()
    await nextTick()
    expect(addListener).toHaveBeenCalledWith(expect.any(Function))
    wrapper.unmount()
    expect(removeListener).toHaveBeenCalledWith(expect.any(Function))
  })

  it('uses removeListener fallback on unmount when removeEventListener missing', async () => {
    const addListener = vi.fn()
    const removeListener = vi.fn()
    ;(window.matchMedia as any).mockImplementationOnce((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener,
      removeListener,
      addEventListener: undefined,
      removeEventListener: undefined,
      dispatchEvent: vi.fn(() => false),
    }))
    const wrapper = mountComponent()
    await nextTick()
    wrapper.unmount()
    expect(removeListener).toHaveBeenCalled()
  })

  it('editingField type radio changes update editingField', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).editField(0)
    await nextTick()
    const radios = wrapper.findAll('input[type="radio"]')
    await radios[0].setValue('fixed')
    expect((wrapper.vm as any).editingField.type).toBe('fixed')
  })
})
