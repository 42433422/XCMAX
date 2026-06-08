import { describe, expect, it } from 'vitest'
import {
  buildGenerateJsonFile,
  detectUserProvidedJsonFile,
  resolveGenerateInputs,
} from './officeGenerateFromText'

describe('officeGenerateFromText', () => {
  it('builds minimal json file with user_query', async () => {
    const f = buildGenerateJsonFile('word', '你好世界')
    expect(f.name).toBe('generate_input.json')
    const body = JSON.parse(await f.text())
    expect(body.user_query).toBe('你好世界')
    expect(body.plain_text).toBe('你好世界')
  })

  it('detects user json attachment', async () => {
    const json = new File(['{"slides":[]}'], 'presentation_full.json', { type: 'application/json' })
    const txt = new File(['x'], 'a.txt', { type: 'text/plain' })
    expect(detectUserProvidedJsonFile([txt, json])?.name).toBe('presentation_full.json')
  })

  it('resolveGenerateInputs prefers user json', () => {
    const json = new File(['{"plain_text":"hi"}'], 'data.json', { type: 'application/json' })
    const r = resolveGenerateInputs({
      format: 'word',
      userText: 'ignored when json',
      attachmentFiles: [json],
    })
    expect(r.usedUserJson).toBe(true)
    expect(r.jsonFile).toBe(json)
    expect(r.inputData.use_llm_from_text).toBe(false)
  })

  it('resolveGenerateInputs builds plaintext payload for ppt', () => {
    const r = resolveGenerateInputs({
      format: 'ppt',
      userText: '三页介绍',
      attachmentFiles: [],
    })
    expect(r.usedUserJson).toBe(false)
    expect(r.inputData.use_llm_from_text).toBe(true)
    expect(r.jsonFile.name).toBe('generate_input.json')
  })
})
