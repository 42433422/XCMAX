import { describe, expect, it } from 'vitest'
import {
  AIOPEN_MCP_SERVER_NAME,
  buildAiopenClientInstalls,
  buildAiAssistantSetupPrompt,
  buildAiopenOneLiner,
  buildCursorDeeplink,
  buildMcpUrlConfig,
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
    const cursor = clients.find((c) => c.id === 'cursor')!
    expect(cursor.installUrl).toMatch(/^cursor:\/\//)
    expect(cursor.mcpJson).toContain('test-key')
  })

  it('cursor deeplink encodes url config', () => {
    const cfg = buildMcpUrlConfig('http://localhost:5100')
    const link = buildCursorDeeplink(AIOPEN_MCP_SERVER_NAME, cfg)
    expect(link).toContain('cursor://anysphere.cursor-deeplink/mcp/install')
    expect(link).toContain('name=xcagi-aiopen')
  })

  it('builds one liner for web ai assistants', () => {
    const line = buildAiopenOneLiner('http://127.0.0.1:5100', 'key1')
    expect(line).toContain('127.0.0.1:5100')
    expect(line).toContain('guide?format=markdown')
    expect(line).toContain('key1')
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

  it('builds ai assistant setup prompt with backend base and json', () => {
    const prompt = buildAiAssistantSetupPrompt({
      backendBase: 'http://127.0.0.1:5100',
      clientId: 'claude',
      apiKey: 'aiopen_test',
    })
    expect(prompt).toContain('127.0.0.1:5100')
    expect(prompt).toContain('mcpServers')
    expect(prompt).toContain('Claude')
    expect(prompt).toContain('aiopen_test')
  })
})
