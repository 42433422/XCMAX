import { describe, expect, it } from 'vitest'
import { parseByokPaste } from './byokEnvImport'

describe('parseByokPaste', () => {
  it('maps .env keys into provider credential entries', () => {
    const result = parseByokPaste(`
      export OPENAI_API_KEY="sk-openai"
      OPENAI_BASE_URL=https://api.example.test/v1
      deepseek=sk-deepseek
    `)

    expect(result.entries).toEqual([
      { provider: 'openai', api_key: 'sk-openai', base_url: 'https://api.example.test/v1' },
      { provider: 'deepseek', api_key: 'sk-deepseek', base_url: null },
    ])
    expect(result.bareKeys).toEqual([])
    expect(result.warnings).toEqual([])
  })

  it('warns about malformed or too-short labelled secrets', () => {
    const result = parseByokPaste('OPENAI_API_KEY=sk')

    expect(result.entries).toEqual([])
    expect(result.bareKeys).toEqual([])
    expect(result.warnings.join('\n')).toContain('密钥过短')
  })

  it('maps newly supported domestic provider aliases', () => {
    const result = parseByokPaste(`
      WENXIN_API_KEY=wenxin-key
      HUNYUAN_API_KEY=hunyuan-key
      zhipu=zhipu-key
    `)

    expect(result.entries).toEqual([
      { provider: 'wenxin', api_key: 'wenxin-key', base_url: null },
      { provider: 'hunyuan', api_key: 'hunyuan-key', base_url: null },
      { provider: 'zhipu', api_key: 'zhipu-key', base_url: null },
    ])
    expect(result.bareKeys).toEqual([])
  })

  it('collects untagged bare keys for backend auto-detection', () => {
    const result = parseByokPaste(`
      sk-bare-key-aaaaaa
      OPENAI_API_KEY=sk-openai
      sk-another-bare-key-bbb
    `)

    expect(result.entries).toEqual([
      { provider: 'openai', api_key: 'sk-openai', base_url: null },
    ])
    expect(result.bareKeys).toEqual(['sk-bare-key-aaaaaa', 'sk-another-bare-key-bbb'])
    expect(result.warnings.join('\n')).not.toContain('跳过')
  })

  it('deduplicates repeated bare keys', () => {
    const result = parseByokPaste(`
      sk-duplicate-key-xx
      sk-duplicate-key-xx
    `)

    expect(result.entries).toEqual([])
    expect(result.bareKeys).toEqual(['sk-duplicate-key-xx'])
  })

  it('still warns when a line is neither NAME=VALUE nor a plausible key', () => {
    const result = parseByokPaste('this is not a key line')

    expect(result.entries).toEqual([])
    expect(result.bareKeys).toEqual([])
    expect(result.warnings.join('\n')).toContain('跳过')
  })
})
