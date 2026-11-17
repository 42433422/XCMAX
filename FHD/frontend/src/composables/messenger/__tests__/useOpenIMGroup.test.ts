import { describe, expect, it, vi } from 'vitest'
import type { MessageItem } from '@openim/wasm-client-sdk'
import { decodeGroupMessage, markGroupRead } from '../useOpenIMGroup'

const session = { enabled: true, userID: 'owner', token: '', platformID: 5,
  apiAddr: '', wsAddr: '', groupID: 'remote', senders: { owner: 'user', worker: 'employee' } }
const row = { id: '1', group_id: 'local', sender_id: 'employee', role: 'ai', body: '已完成' }
function message(patch = {}): MessageItem {
  return { groupID: 'remote', sendID: 'worker', customElem: {
    extension: 'xcagi-group-v1', data: JSON.stringify(row), description: '',
  }, ...patch } as MessageItem
}
describe('OpenIM employee message boundary', () => {
  it('accepts the server sender identity and source group', () => {
    expect(decodeGroupMessage(message(), 'local', session)).toEqual(row)
  })
  it('rejects a client pretending to be an employee', () => {
    expect(decodeGroupMessage(message({ sendID: 'owner' }), 'local', session)).toBeNull()
  })
  it('rejects other groups and malformed custom messages', () => {
    expect(decodeGroupMessage(message({ groupID: 'foreign' }), 'local', session)).toBeNull()
    expect(decodeGroupMessage(message({ customElem: { data: 'broken' } }), 'local', session)).toBeNull()
  })
})

it('treats the SDK already-read response as success but preserves connection failures', async () => {
  const client = { markConversationMessageAsRead: vi.fn().mockRejectedValueOnce({ errCode: 10303 })
    .mockRejectedValueOnce({ errCode: 1506 }) };
  await expect(markGroupRead(client, 'group')).resolves.toBeUndefined();
  await expect(markGroupRead(client, 'group')).rejects.toEqual({ errCode: 1506 });
});

it('rejects malformed payloads and forged user roles even from a known SDK sender', () => {
  const custom = (data: string) => message({ customElem: { extension: 'xcagi-group-v1', data } })
  expect(decodeGroupMessage(custom('{invalid'), 'local', session)).toBeNull()
  expect(decodeGroupMessage(custom(JSON.stringify({ ...row, group_id: 'foreign' })), 'local', session)).toBeNull()
  expect(decodeGroupMessage(custom(JSON.stringify({ ...row, role: 'user' })), 'local', session)).toBeNull()
})
