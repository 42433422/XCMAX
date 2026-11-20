import { describe, expect, it } from 'vitest'
import {
  AIOPEN_MCP_SERVER_NAME,
  buildAiopenClientInstalls,
  buildAiopenOneLiner,
  markAiopenClientInstalled,
  readAiopenInstalledClients,
  unmarkAiopenClientInstalled,
} from './aiopenMcpInstall'

describe('aiopenMcpInstall', () => {
  it('builds configs for all supported AI clients', () => {
    const clients = buildAiopenClientInstalls('http://127.0.0.1:5100', 'test-key')
    expect(clients.map((c) => c.id)).toEqual(['cursor', 'claude', 'vscode', 'windsurf', 'trae', 'generic'])
    for (const client of clients) {
      expect(client.mcpJson).toContain(AIOPEN_MCP_SERVER_NAME)
      expect(client.mcpJson).toContain('mcpServers')
    }
    expect(clients.every((client) => client.mcpJson.includes('test-key'))).toBe(true)
  })

  it('keeps credentials in the copied JSON and out of installation links', () => {
    const clients = buildAiopenClientInstalls('http://localhost:5100', 'test-key')
    expect(clients.every((client) => !('installUrl' in client) && !('installFallbackUrl' in client))).toBe(true)
  })

  it('builds one liner with a complete local HTTP config', () => {
    const line = buildAiopenOneLiner('http://127.0.0.1:5100', '', 'test-key')
    expect(line).toContain('127.0.0.1:5100')
    expect(line).toContain('guide?format=markdown')
    expect(line).toContain('本地配置')
    expect(line).toContain('tools/list')
    expect(line).toContain('ui_sessions')
    const [, config] = line.split('```json\n')
    expect(JSON.parse(config.replace(/\n```$/, ''))).toEqual({
      mcpServers: {
        [AIOPEN_MCP_SERVER_NAME]: {
          url: 'http://127.0.0.1:5100/api/aiopen/mcp',
          headers: { 'X-AIOPEN-Key': 'test-key' },
        },
      },
    })
  })

  it('one liner points empty-screen hint at the current console', () => {
    const admin = buildAiopenOneLiner('http://127.0.0.1:5100', 'http://localhost:5011/admin')
    expect(admin).toContain('http://localhost:5011/admin')
    const host = buildAiopenOneLiner(
      'http://127.0.0.1:5100',
      'http://127.0.0.1:42423/ai-ecosystem'
    )
    expect(host).toContain('/ai-ecosystem')
  })

  it('toggles installed client markers in localStorage', () => {
    localStorage.clear()
    markAiopenClientInstalled('cursor')
    markAiopenClientInstalled('claude')
    expect(readAiopenInstalledClients()).toEqual(['cursor', 'claude'])

    unmarkAiopenClientInstalled('cursor')
    expect(readAiopenInstalledClients()).toEqual(['claude'])

    unmarkAiopenClientInstalled('claude')
    expect(readAiopenInstalledClients()).toEqual([])
    expect(localStorage.getItem('aiopen_cursor_installed')).toBeNull()
  })

})
