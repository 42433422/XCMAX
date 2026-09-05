import { defineComponent, h, KeepAlive, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { useEtlRollbackPermission } from './useEtlRollbackPermission'

const { currentUserMock } = vi.hoisted(() => ({ currentUserMock: vi.fn() }))
vi.mock('@/api/auth', () => ({ authApi: { getCurrentUser: currentUserMock } }))

const granted = { success: true, data: { permissions: ['etl.rollback'] } }
const denied = { success: true, data: { permissions: ['etl.execute'] } }

function permissionView() {
  const visible = ref(true)
  const Probe = defineComponent({
    setup() {
      const permission = useEtlRollbackPermission()
      return () => h('button', { disabled: !permission.canRollback.value }, permission.rollbackPermissionMessage.value)
    },
  })
  const Other = defineComponent({ render: () => h('div', 'other page') })
  const wrapper = mount(defineComponent({
    setup: () => () => h(KeepAlive, null, { default: () => visible.value ? h(Probe) : h(Other) }),
  }))
  return { wrapper, visible }
}

describe('effective rollback permission lifecycle', () => {
  it('refreshes backend permission after returning to a kept-alive ETL page', async () => {
    currentUserMock.mockReset().mockResolvedValueOnce(granted).mockResolvedValueOnce(denied)
    const { wrapper, visible } = permissionView()
    try {
      await flushPromises()
      expect(wrapper.find('button').attributes('disabled')).toBeUndefined()
      visible.value = false
      await flushPromises()
      visible.value = true
      await flushPromises()
      expect(wrapper.find('button').attributes('disabled')).toBeDefined()
      expect(wrapper.text()).toContain('需要管理员授予撤销权限')
      expect(currentUserMock).toHaveBeenCalledTimes(2)
    } finally {
      wrapper.unmount()
    }
  })

  it('ignores a previous activation grant that arrives after the current permission denial', async () => {
    let resolveOld!: (result: typeof granted) => void
    const old = new Promise<typeof granted>((resolve) => { resolveOld = resolve })
    currentUserMock.mockReset().mockReturnValueOnce(old).mockResolvedValueOnce(denied)
    const { wrapper, visible } = permissionView()
    try {
      await flushPromises()
      expect(wrapper.find('button').attributes('disabled')).toBeDefined()
      visible.value = false
      await flushPromises()
      visible.value = true
      await flushPromises()
      resolveOld(granted)
      await flushPromises()
      expect(wrapper.find('button').attributes('disabled')).toBeDefined()
      expect(wrapper.text()).toContain('需要管理员授予撤销权限')
    } finally {
      wrapper.unmount()
    }
  })
})
