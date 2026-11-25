import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useChatRequest, type ChatRequestScope } from './useChatRequest'
import { addChatArtifactIds, clearChatArtifactIds, listChatArtifactIds } from '@/utils/chatArtifactContext'

const { send } = vi.hoisted(() => ({ send: vi.fn() }))
vi.mock('@/api/chat', () => ({ default: { sendUnifiedChat: send, sendUnifiedChatBatch: send } }))
vi.mock('./useApprovalMode', () => ({ useApprovalMode: () => ({ state: { enabled: false } }) }))
const scope = (turnId: string): ChatRequestScope => ({ sessionId: 'conversation', messages: [], turnId })
function setup() {
  return useChatRequest({ messages: ref([]), sessionId: ref('conversation'), lastRequestContextSummary: ref(''), injectExcelContextPayload: () => false, consumeMultimodalIntoPlannerContext: () => {} })
}
function artifacts(body: Record<string, unknown>) { return (body.context as Record<string, unknown>).artifact_ids }
beforeEach(() => { clearChatArtifactIds(); send.mockReset() })

describe('request attachment batch lifecycle', () => {
  it('does not repeat successful previous-turn attachments on a fresh message', async () => {
    const request = setup()
    send.mockResolvedValue({ success: true })
    addChatArtifactIds(['first'])
    await request.requestChatByMode('first', {}, undefined, scope('turn-first'))
    await request.requestChatByMode('next', {}, undefined, scope('turn-next'))
    expect(artifacts(send.mock.calls[0][0])).toEqual(['first'])
    expect(artifacts(send.mock.calls[1][0])).toBeUndefined()
  })

  it('retains the same attachments on an immediate failed-request retry', async () => {
    const request = setup()
    send.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ success: true })
    addChatArtifactIds(['first'])
    await expect(request.requestChatByMode('first', {}, undefined, scope('turn-first'))).rejects.toThrow('offline')
    await request.requestChatByMode('retry', {}, { retryOf: 'turn-first' }, scope('turn-retry'))
    expect(artifacts(send.mock.calls[1][0])).toEqual(['first'])
  })

  it.each(['single', 'batch'])('does not erase the next upload when an older %s request completes', async mode => {
    const request = setup()
    let finish!: (value: unknown) => void
    send.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    addChatArtifactIds(['first'])
    const pending = mode === 'single' ? request.requestChatByMode('first', {}, undefined, scope('turn-first')) : request.requestChatByModeBatch(['first'], {}, scope('turn-first'))
    addChatArtifactIds(['next'])
    finish({ success: true })
    await pending
    expect(listChatArtifactIds()).toEqual(['next'])
  })

  it('retries the failed turn batch, not a newly selected attachment batch', async () => {
    const request = setup()
    send.mockRejectedValueOnce(new Error('offline'))
    addChatArtifactIds(['first'])
    await expect(request.requestChatByMode('first', {}, undefined, scope('turn-first'))).rejects.toThrow('offline')
    addChatArtifactIds(['next'])
    const { body } = request.buildPlannerChatRequestPayload('retry', { retryOf: 'turn-first' }, scope('turn-retry'))
    expect(artifacts(body)).toEqual(['first'])
    expect(listChatArtifactIds()).toEqual(['next'])
  })

  it('rebuilding the same turn for stream reconnect preserves its attachment batch', () => {
    const request = setup()
    addChatArtifactIds(['first'])
    request.buildPlannerChatRequestPayload('first', undefined, scope('turn-first'))
    expect(artifacts(request.buildPlannerChatRequestPayload('first', undefined, scope('turn-first')).body)).toEqual(['first'])
  })
  it('does not clear a reuploaded identical ID when the old request completes', async () => {
    const request = setup()
    let finish!: (value: unknown) => void
    send.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    addChatArtifactIds(['same'])
    const pending = request.requestChatByMode('first', {}, undefined, scope('first'))
    addChatArtifactIds(['same'])
    finish({ success: true })
    await pending
    expect(listChatArtifactIds()).toEqual(['same'])
    expect(artifacts(request.buildPlannerChatRequestPayload('next', undefined, scope('next')).body)).toEqual(['same'])
  })

  it('keeps a completed turn snapshot available for an explicit retry', async () => {
    const request = setup()
    send.mockResolvedValue({ success: true })
    addChatArtifactIds(['first'])
    await request.requestChatByMode('first', {}, undefined, scope('first'))
    addChatArtifactIds(['next'])
    await request.requestChatByMode('retry', {}, { retryOf: 'first' }, scope('retry'))
    expect(artifacts(send.mock.calls[1][0])).toEqual(['first'])
    expect(listChatArtifactIds()).toEqual(['next'])
  })

  it('never substitutes new uploads for an unknown retry turn', () => {
    const request = setup()
    addChatArtifactIds(['next'])
    expect(artifacts(request.buildPlannerChatRequestPayload('retry', { retryOf: 'unknown' }, scope('retry')).body)).toBeUndefined()
    expect(listChatArtifactIds()).toEqual(['next'])
  })

  it('retains independent batches when overlapping requests complete out of order', async () => {
    const request = setup()
    let finishFirst!: (value: unknown) => void
    send.mockReturnValueOnce(new Promise(resolve => { finishFirst = resolve })).mockRejectedValueOnce(new Error('offline'))
    addChatArtifactIds(['first'])
    const pending = request.requestChatByMode('first', {}, undefined, scope('first'))
    addChatArtifactIds(['second'])
    await expect(request.requestChatByMode('second', {}, undefined, scope('second'))).rejects.toThrow('offline')
    finishFirst({ success: true }); await pending
    expect(artifacts(request.buildPlannerChatRequestPayload('retry second', { retryOf: 'second' }, scope('retry')).body)).toEqual(['second'])
    expect(listChatArtifactIds()).toEqual(['second'])
  })

  it('keeps old visible turns retryable but releases snapshots removed from conversation history', () => {
    const request = setup()
    const message = (turnId: string) => ({ role: 'user', content: turnId, time: '12:00', turnId })
    addChatArtifactIds(['old-file'])
    request.buildPlannerChatRequestPayload('old', undefined, { ...scope('old'), messages: [message('old')] })
    const history = [message('old'), ...Array.from({ length: 45 }, (_, n) => message(`turn-${n}`))]
    request.buildPlannerChatRequestPayload('latest', undefined, { ...scope('latest'), messages: history })
    expect(artifacts(request.buildPlannerChatRequestPayload('retry old', { retryOf: 'old' }, { ...scope('retry'), messages: history }).body)).toEqual(['old-file'])
    request.buildPlannerChatRequestPayload('new history', undefined, { ...scope('new'), messages: [message('new')] })
    expect(artifacts(request.buildPlannerChatRequestPayload('retry removed', { retryOf: 'old' }, scope('retry-removed')).body)).toBeUndefined()
  })

  it('keeps an empty turn empty on reconnect without consuming a later upload', () => {
    const request = setup()
    request.buildPlannerChatRequestPayload('no attachment', undefined, scope('empty'))
    addChatArtifactIds(['later'])
    expect(artifacts(request.buildPlannerChatRequestPayload('reconnect', undefined, scope('empty')).body)).toBeUndefined()
    expect(listChatArtifactIds()).toEqual(['later'])
    expect(artifacts(request.buildPlannerChatRequestPayload('new', undefined, scope('new')).body)).toEqual(['later'])
  })

})
