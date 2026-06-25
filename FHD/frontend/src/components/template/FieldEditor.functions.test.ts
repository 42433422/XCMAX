import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import FieldEditor from './FieldEditor.vue'

vi.mock('@/utils/appDialog', () => ({
  appConfirm: vi.fn().mockResolvedValue(true),
  appAlert: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/composables/useResizablePane', () => ({
  useResizablePane: () => ({
    paneStyle: { width: '420px' },
    startResize: vi.fn(),
    resetSize: vi.fn(),
    stopResize: vi.fn(),
  }),
}))

vi.mock('@/components/PaneResizeHandle.vue', () => ({
  default: {
    name: 'PaneResizeHandle',
    template: '<div class="pane-resize-handle-stub" />',
    emits: ['resize-start', 'reset'],
  },
}))

vi.mock('./ExcelPreview.vue', () => ({
  default: { name: 'ExcelPreview', template: '<div class="excel-preview-stub" />' },
}))

vi.mock('./LabelPreview.vue', () => ({
  default: { name: 'LabelPreview', template: '<div class="label-preview-stub" />' },
}))

function mountFieldEditor(props: Record<string, unknown> = {}) {
  return mount(FieldEditor, {
    props: {
      fields: [
        { label: '品名', value: '运动鞋', type: 'dynamic' },
        { label: '规格', value: '42码', type: 'fixed' },
      ],
      templateType: 'excel',
      ...props,
    },
  })
}

describe('FieldEditor.vue functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('selectField', () => {
    it('sets editingIndex to the given index', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.selectField(1)
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.editingIndex).toBe(1)
    })

    it('sets editingIndex to 0', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.selectField(0)
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.editingIndex).toBe(0)
    })

    it('marks the field item as active via click', async () => {
      const wrapper = mountFieldEditor()
      const items = wrapper.findAll('.field-item')
      await items[1].trigger('click')
      expect(wrapper.vm.editingIndex).toBe(1)
    })
  })

  describe('editField', () => {
    it('opens edit modal with a copy of the field at index', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.editField(0)
      await wrapper.vm.$nextTick()
      expect(wrapper.vm.editingIndex).toBe(0)
      expect(wrapper.vm.editingField).toEqual({
        label: '品名',
        value: '运动鞋',
        type: 'dynamic',
      })
    })

    it('editingField is a copy not a reference', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.editField(0)
      // @ts-expect-error mutate internal
      wrapper.vm.editingField.label = '改后'
      // 原始 props 不应被改
      expect(wrapper.props('fields')[0].label).toBe('品名')
    })

    it('opens modal via pencil button click', async () => {
      const wrapper = mountFieldEditor()
      const editBtn = wrapper.findAll('.field-actions .btn-icon')[0]
      await editBtn.trigger('click')
      expect(wrapper.vm.editingField).toBeTruthy()
      expect(wrapper.find('.field-edit-modal').exists()).toBe(true)
    })
  })

  describe('closeEditModal', () => {
    it('clears editingField', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.editField(0)
      expect(wrapper.vm.editingField).not.toBeNull()
      // @ts-expect-error access internal method
      wrapper.vm.closeEditModal()
      expect(wrapper.vm.editingField).toBeNull()
    })

    it('hides modal via close button', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.editField(0)
      await wrapper.vm.$nextTick()
      await wrapper.find('.modal-close').trigger('click')
      expect(wrapper.vm.editingField).toBeNull()
    })

    it('hides modal via overlay click', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.editField(0)
      await wrapper.vm.$nextTick()
      await wrapper.find('.modal-overlay').trigger('click')
      expect(wrapper.vm.editingField).toBeNull()
    })

    it('hides modal via cancel button', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.editField(0)
      await wrapper.vm.$nextTick()
      const cancelBtn = wrapper.findAll('.modal-footer .btn').find((b) => b.text().includes('取消'))
      await cancelBtn?.trigger('click')
      expect(wrapper.vm.editingField).toBeNull()
    })
  })

  describe('saveFieldEdit', () => {
    it('emits update-field with index and edited field copy', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.editField(0)
      // @ts-expect-error mutate internal
      wrapper.vm.editingField.label = '新品名'
      // @ts-expect-error access internal method
      wrapper.vm.saveFieldEdit()
      await wrapper.vm.$nextTick()
      const emitted = wrapper.emitted('update-field')
      expect(emitted).toBeTruthy()
      expect(emitted![0][0]).toBe(0)
      expect(emitted![0][1]).toMatchObject({ label: '新品名' })
    })

    it('closes modal after save', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.editField(0)
      // @ts-expect-error access internal method
      wrapper.vm.saveFieldEdit()
      expect(wrapper.vm.editingField).toBeNull()
    })

    it('does nothing when editingIndex is null', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.editingIndex = null
      // @ts-expect-error access internal method
      wrapper.vm.editingField = { label: 'x', value: 'y', type: 'fixed' }
      // @ts-expect-error access internal method
      wrapper.vm.saveFieldEdit()
      expect(wrapper.emitted('update-field')).toBeFalsy()
    })

    it('emits update-field via save button click', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.editField(1)
      await wrapper.vm.$nextTick()
      const saveBtn = wrapper.findAll('.modal-footer .btn').find((b) => b.text().includes('保存'))
      await saveBtn?.trigger('click')
      expect(wrapper.emitted('update-field')).toBeTruthy()
    })
  })

  describe('toggleType', () => {
    it('emits update-field switching fixed to dynamic', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.toggleType(1) // index 1 is fixed
      const emitted = wrapper.emitted('update-field')
      expect(emitted).toBeTruthy()
      expect(emitted![0][0]).toBe(1)
      expect(emitted![0][1]).toMatchObject({ type: 'dynamic' })
    })

    it('emits update-field switching dynamic to fixed', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.toggleType(0) // index 0 is dynamic
      const emitted = wrapper.emitted('update-field')
      expect(emitted![0][1]).toMatchObject({ type: 'fixed' })
    })

    it('preserves other field properties when toggling', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.toggleType(0)
      const emitted = wrapper.emitted('update-field')
      expect(emitted![0][1]).toMatchObject({
        label: '品名',
        value: '运动鞋',
        type: 'fixed',
      })
    })

    it('toggles via badge click', async () => {
      const wrapper = mountFieldEditor()
      const badge = wrapper.findAll('.type-badge')[0]
      await badge.trigger('click')
      expect(wrapper.emitted('update-field')).toBeTruthy()
    })
  })

  describe('deleteField', () => {
    it('emits delete-field when confirmed', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      await wrapper.vm.deleteField(0)
      const emitted = wrapper.emitted('delete-field')
      expect(emitted).toBeTruthy()
      expect(emitted![0][0]).toBe(0)
    })

    it('does not emit when not confirmed', async () => {
      const { appConfirm } = await import('@/utils/appDialog')
      ;(appConfirm as ReturnType<typeof vi.fn>).mockResolvedValueOnce(false)
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      await wrapper.vm.deleteField(0)
      expect(wrapper.emitted('delete-field')).toBeFalsy()
    })

    it('clears editingIndex when deleting the active field', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.selectField(0)
      // @ts-expect-error access internal method
      await wrapper.vm.deleteField(0)
      expect(wrapper.vm.editingIndex).toBeNull()
    })

    it('keeps editingIndex when deleting a different field', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.selectField(1)
      // @ts-expect-error access internal method
      await wrapper.vm.deleteField(0)
      expect(wrapper.vm.editingIndex).toBe(1)
    })

    it('deletes via trash button click', async () => {
      const wrapper = mountFieldEditor()
      const deleteBtn = wrapper.findAll('.btn-icon.btn-danger')[0]
      await deleteBtn.trigger('click')
      await wrapper.vm.$nextTick()
      expect(wrapper.emitted('delete-field')).toBeTruthy()
    })
  })

  describe('addField', () => {
    it('emits add-field with default new field', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.addField()
      const emitted = wrapper.emitted('add-field')
      expect(emitted).toBeTruthy()
      expect(emitted![0][0]).toMatchObject({
        label: '新字段',
        value: '示例值',
        type: 'dynamic',
      })
    })

    it('emits add-field via button click', async () => {
      const wrapper = mountFieldEditor()
      const addBtn = wrapper.find('.add-field-actions .btn')
      await addBtn.trigger('click')
      expect(wrapper.emitted('add-field')).toBeTruthy()
    })
  })

  describe('onFieldChange', () => {
    it('emits fields-change with a copy of fields', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.onFieldChange()
      const emitted = wrapper.emitted('fields-change')
      expect(emitted).toBeTruthy()
      expect(Array.isArray(emitted![0][0])).toBe(true)
      expect(emitted![0][0]).toHaveLength(2)
    })

    it('emits a copy not the original array reference', async () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      wrapper.vm.onFieldChange()
      const emitted = wrapper.emitted('fields-change')
      expect(emitted![0][0]).not.toBe(wrapper.props('fields'))
    })
  })

  describe('getFields', () => {
    it('returns a copy of fields', () => {
      const wrapper = mountFieldEditor()
      // @ts-expect-error access internal method
      const result = wrapper.vm.getFields()
      expect(result).toEqual(wrapper.props('fields'))
      expect(result).not.toBe(wrapper.props('fields'))
    })

    it('returns empty array when fields prop is empty', () => {
      const wrapper = mountFieldEditor({ fields: [] })
      // @ts-expect-error access internal method
      const result = wrapper.vm.getFields()
      expect(result).toEqual([])
    })
  })

  describe('rendering', () => {
    it('renders empty state when no fields', () => {
      const wrapper = mountFieldEditor({ fields: [] })
      expect(wrapper.find('.empty-fields').exists()).toBe(true)
      expect(wrapper.text()).toContain('暂无字段')
    })

    it('renders word preview when templateType is word', () => {
      const wrapper = mountFieldEditor({ templateType: 'word' })
      expect(wrapper.find('.word-preview-box').exists()).toBe(true)
    })

    it('renders label preview when templateType is label', () => {
      const wrapper = mountFieldEditor({ templateType: 'label' })
      expect(wrapper.find('.label-preview-stub').exists()).toBe(true)
    })

    it('renders excel preview by default', () => {
      const wrapper = mountFieldEditor({ templateType: 'excel' })
      expect(wrapper.find('.excel-preview-stub').exists()).toBe(true)
    })

    it('shows fixed badge for fixed type field', () => {
      const wrapper = mountFieldEditor()
      const badges = wrapper.findAll('.type-badge')
      expect(badges[1].text()).toBe('固定')
    })

    it('shows dynamic badge for dynamic type field', () => {
      const wrapper = mountFieldEditor()
      const badges = wrapper.findAll('.type-badge')
      expect(badges[0].text()).toBe('可变')
    })
  })
})
