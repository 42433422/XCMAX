import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import { confirmDanger, resolveDangerConfirm } from '../composables/useDangerConfirm'
import AppConfirmDialog from './AppConfirmDialog.vue'

let wrapper: VueWrapper | undefined
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  // A failed or interrupted test must not leave a pending global confirmation.
  resolveDangerConfirm(false)
})

async function openDialog() {
  wrapper = mount(AppConfirmDialog, {
    attachTo: document.body,
    global: { stubs: { teleport: true } },
  })
  const answer = confirmDanger({
    title: '删除员工',
    message: '该操作需再次确认',
    destructive: true,
  })
  await flushPromises()
  return { answer, dialog: wrapper.getComponent(ElDialog) }
}

describe('全局敏感操作确认弹窗', () => {
  it('复用 Element Plus 的焦点约束、Escape、遮罩及滚动锁，不自动执行', async () => {
    const { answer, dialog } = await openDialog()
    expect(dialog.props('modelValue')).toBe(true)
    expect(dialog.props('closeOnPressEscape')).toBe(true)
    expect(dialog.props('closeOnClickModal')).toBe(true)
    expect(dialog.props('lockScroll')).toBe(true)
    expect(dialog.props('showClose')).toBe(false)
    expect(wrapper!.text()).toContain('该操作需再次确认')
    dialog.vm.$emit('opened')
    await flushPromises()
    expect(document.activeElement?.textContent?.trim()).toBe('取消')
    expect(wrapper!.get('[data-dialog-initial-focus]').element).toBe(document.activeElement)
    await wrapper!.get('.app-confirm-dialog__cancel').trigger('click')
    expect(await answer).toBe(false)
  })

  it('Escape / 遮罩关闭总是拒绝操作，只有显式确认按钮允许通过', async () => {
    const first = await openDialog()
    const beforeClose = first.dialog.props('beforeClose') as (done: () => void) => void
    const done = vi.fn()
    beforeClose(done)
    expect(done).toHaveBeenCalledOnce()
    expect(await first.answer).toBe(false)
    wrapper!.unmount()
    const second = await openDialog()
    await wrapper!.get('.app-confirm-dialog__confirm').trigger('click')
    expect(await second.answer).toBe(true)
  })
  it('simultaneous sensitive confirmations reject the previous pending action', async () => {
    const prior = confirmDanger({ title: '删除 A', message: '第一次请求' })
    const current = confirmDanger({ title: '删除 B', message: '第二次请求' })
    expect(await prior).toBe(false)
    resolveDangerConfirm(false)
    expect(await current).toBe(false)
  })

})
