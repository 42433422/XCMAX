import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import GroupAvatar from './GroupAvatar.vue'
const members = Array.from({ length: 10 }, (_, n) => ({ employee_id: `e${n}`, name: `成员${n}`, avatar: `/avatars/${n}.png`, mod_id: '', summary: '' }))
it('uses at most nine actual members and updates when membership changes', async () => {
  const wrapper = mount(GroupAvatar, { props: { name: '员工大群', members } })
  expect(wrapper.findAll('img').map(img => img.attributes('src'))).toEqual(members.slice(0, 9).map(member => member.avatar))
  await wrapper.setProps({ members: [members[9]] })
  expect(wrapper.findAll('img')).toHaveLength(1)
  expect(wrapper.get('img').attributes('src')).toBe('/avatars/9.png')
  await wrapper.get('img').trigger('error')
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.text()).toBe('成')
  await wrapper.setProps({ members: [] })
  expect(wrapper.text()).toBe('员')
  wrapper.unmount()
})
