import { onUnmounted, reactive, ref, watch } from 'vue'
import type { MessageItem, ConversationItem, WSEvent, getSDK as GetSDK } from '@openim/wasm-client-sdk'
import { apiFetch } from '@/utils/apiBase'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import type { AiGroupMessage } from '@/api/aiGroups'

type Session = { enabled: boolean; userID: string; token: string; platformID: number;
  apiAddr: string; wsAddr: string; groupID: string; senders: Record<string, string>; groups?: Record<string, string> }
type SDK = ReturnType<typeof GetSDK>
export const openimGroupUnread = reactive<Record<string, number>>({})
let runtime: Promise<typeof import('@openim/wasm-client-sdk')> | undefined
let sdk: SDK | undefined
let owner = ''
let ownerToken = ''
let connection: Promise<void> = Promise.resolve()
const groupIDs = new Map<string, string>()

async function loadRuntime() {
  if (!runtime) {
    runtime = new Promise<void>((resolve, reject) => {
      const script = document.createElement('script')
      script.src = `${import.meta.env.BASE_URL}openim/wasm_exec.js`
      script.onload = () => resolve()
      script.onerror = () => { script.remove(); reject(new Error('消息组件加载失败')) }
      document.head.append(script)
    }).then(() => import('@openim/wasm-client-sdk')).catch(error => { runtime = undefined; throw error })
  }
  return runtime
}

function unread(items: ConversationItem[]) {
  for (const item of items) {
    const id = groupIDs.get(item.groupID)
    if (id) openimGroupUnread[id] = item.unreadCount
  }
}

watch(productReadAccountEpoch, () => {
  owner = ''
  ownerToken = ''
  groupIDs.clear()
  for (const key of Object.keys(openimGroupUnread)) delete openimGroupUnread[key]
  connection = connection.catch(() => undefined).then(async () => { if (sdk) await sdk.logout() })
})

export function decodeGroupMessage(item: MessageItem, groupId: string, session: Session): AiGroupMessage | null {
  if (item.groupID !== session.groupID || item.customElem?.extension !== 'xcagi-group-v1') return null
  try {
    const row = JSON.parse(item.customElem.data) as AiGroupMessage
    if (!row.id || typeof row.body !== 'string' || row.group_id !== groupId) return null
    if (session.senders[item.sendID] !== row.sender_id) return null
    if ((row.role === 'user') !== (item.sendID === session.userID)) return null
    return row
  } catch { return null }
}

export async function markGroupRead(client: Pick<SDK, 'markConversationMessageAsRead'>, id: string) {
  try { await client.markConversationMessageAsRead(id) }
  catch (failure) {
    // The pinned SDK reports an already-read conversation as 10303.
    if ((failure as { errCode?: number }).errCode !== 10303) throw failure
  }
}

export function useOpenIMGroup(receive: (rows: AiGroupMessage[]) => void) {
  const connected = ref(false)
  const active = ref(false)
  const error = ref('')
  const hasOlder = ref(false)
  let session: Session | undefined
  let localGroup = ''
  let conversationID = ''
  let oldest = ''
  let generation = 0
  let unsubscribe = () => {}

  async function history(older = false) {
    if (!sdk || !session || !conversationID) return
    const captured = generation
    const page = await sdk.getAdvancedHistoryMessageList({
      conversationID, startClientMsgID: older ? oldest : '', count: 100, viewType: 0,
    })
    if (captured !== generation) return
    if (page.data.errCode) throw new Error('历史消息加载失败')
    hasOlder.value = !page.data.isEnd
    oldest = page.data.messageList[0]?.clientMsgID || ''
    receive(page.data.messageList.map(item => decodeGroupMessage(item, localGroup, session!))
      .filter((row): row is AiGroupMessage => row !== null))
    error.value = ''
    if (document.visibilityState === 'visible') {
      try { await markGroupRead(sdk, conversationID) }
      catch { error.value = '已读状态同步失败，请重新连接' }
    }
  }

  async function start(groupId: string): Promise<boolean> {
    const captured = ++generation
    unsubscribe()
    active.value = false
    connected.value = false
    error.value = ''
    const epoch = productReadAccountEpoch.value
    // Retire the old platform session before the host issues its replacement token.
    connection = connection.catch(() => undefined).then(async () => {
      if (sdk) await sdk.logout().catch(() => undefined)
      owner = ''
      ownerToken = ''
    })
    await connection
    if (captured !== generation || epoch !== productReadAccountEpoch.value) return true
    const response = await apiFetch(`/api/admin/ai-groups/${encodeURIComponent(groupId)}/transport`, { method: 'POST' })
    if (!response.ok) throw new Error('消息服务连接失败，请重新连接')
    const data = await response.json() as Session
    if (captured !== generation || epoch !== productReadAccountEpoch.value) return true
    if (!data.enabled) return false
    active.value = true
    session = data
    localGroup = groupId
    groupIDs.set(data.groupID, groupId)
    for (const [remote, local] of Object.entries(data.groups || {})) groupIDs.set(remote, local)
    let module: Awaited<ReturnType<typeof loadRuntime>>
    try {
      // Probe the existing CSP before the SDK swallows asynchronous WASM failures.
      await WebAssembly.compile(Uint8Array.of(0, 97, 115, 109, 1, 0, 0, 0))
      module = await loadRuntime()
      const { getSDK, CbEvents } = module
      if (captured !== generation) return true
      if (!sdk) {
        const base = `${import.meta.env.BASE_URL}openim/`
        sdk = getSDK({ coreWasmPath: `${base}openIM.wasm`, sqlWasmPath: `${base}sql-wasm.wasm` })
        sdk.on(CbEvents.OnConversationChanged, event => unread(event.data))
        sdk.on(CbEvents.OnNewConversation, event => unread(event.data))
      }
    } catch {
      if (captured !== generation || epoch !== productReadAccountEpoch.value) return true
      unsubscribe()
      session = undefined
      active.value = false
      connected.value = false
      error.value = '即时消息连接不可用，已切换为主机消息同步'
      return false
    }
    const { CbEvents } = module
    connection = connection.catch(() => undefined).then(async () => {
      if (epoch !== productReadAccountEpoch.value || captured !== generation) return
      if (owner === data.userID && ownerToken === data.token) return
      owner = ''
      ownerToken = ''
      await sdk!.login({ userID: data.userID, token: data.token, platformID: data.platformID,
        apiAddr: data.apiAddr, wsAddr: data.wsAddr, isLogStandardOutput: false, logLevel: 0 })
      owner = data.userID
      ownerToken = data.token
    })
    await connection
    if (captured !== generation || epoch !== productReadAccountEpoch.value) return true
    const onMessage = (event: WSEvent<MessageItem>) => {
      if (captured !== generation || epoch !== productReadAccountEpoch.value) return
      const row = decodeGroupMessage(event.data, groupId, data)
      if (!row) return
      receive([row])
      if (document.visibilityState === 'visible') void markGroupRead(sdk!, conversationID).catch(() => { error.value = '已读状态同步失败' })
    }
    const current = () => captured === generation && epoch === productReadAccountEpoch.value
    const reconnect = () => { if (!current()) return; connected.value = true; void history().catch(() => { error.value = '历史消息同步失败，请重新连接' }) }
    const disconnect = () => { if (current()) connected.value = false }
    const expired = () => { if (!current()) return; owner = ''; connected.value = false; error.value = '消息连接已失效，请重新连接' }
    sdk.on(CbEvents.OnRecvNewMessage, onMessage)
    sdk.on(CbEvents.OnConnectSuccess, reconnect)
    sdk.on(CbEvents.OnConnecting, disconnect)
    sdk.on(CbEvents.OnConnectFailed, disconnect)
    sdk.on(CbEvents.OnKickedOffline, expired)
    sdk.on(CbEvents.OnUserTokenExpired, expired)
    sdk.on(CbEvents.OnUserTokenInvalid, expired)
    const visibility = () => { if (document.visibilityState === 'visible' && connected.value) void history().catch(() => { error.value = '历史消息同步失败，请重新连接' }) }
    document.addEventListener('visibilitychange', visibility)
    unsubscribe = () => {
      sdk?.off(CbEvents.OnRecvNewMessage, onMessage)
      sdk?.off(CbEvents.OnConnectSuccess, reconnect)
      sdk?.off(CbEvents.OnConnecting, disconnect)
      sdk?.off(CbEvents.OnConnectFailed, disconnect)
      sdk?.off(CbEvents.OnKickedOffline, expired)
      sdk?.off(CbEvents.OnUserTokenExpired, expired)
      sdk?.off(CbEvents.OnUserTokenInvalid, expired)
      document.removeEventListener('visibilitychange', visibility)
    }
    const conversation = await sdk.getOneConversation({ sourceID: data.groupID, sessionType: 3 })
    if (!current()) return true
    conversationID = conversation.data.conversationID
    const conversations = await sdk.getAllConversationList()
    if (!current()) return true
    unread(conversations.data)
    await history()
    if (!current()) return true
    connected.value = true
    return true
  }
  watch(productReadAccountEpoch, () => {
    generation++; unsubscribe()
    session = undefined
    localGroup = ''; conversationID = ''; oldest = ''
    active.value = false; connected.value = false; hasOlder.value = false
    error.value = '账号已切换，请重新打开会话'
  }, { flush: 'sync' })
  onUnmounted(() => { generation++; unsubscribe() })
  return { start, history, connected, active, error, hasOlder }
}
