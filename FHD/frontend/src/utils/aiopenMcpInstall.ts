/** AIOPEN MCP 多客户端安装配置（客户端生成，不依赖 /api/aiopen/install） */

export const AIOPEN_MCP_SERVER_NAME = 'xcagi-aiopen'

export type McpUrlConfig = {
  url: string
  headers?: { 'X-AIOPEN-Key': string }
}

export type McpCommandConfig = {
  command: string
  args: string[]
  env?: Record<string, string>
}

export type AiMcpClientId = 'cursor' | 'claude' | 'vscode' | 'windsurf' | 'trae' | 'generic'

export type AiMcpClientInstall = {
  id: AiMcpClientId
  name: string
  icon: string
  configPath: string
  hint: string
  transport: 'url' | 'mcp_remote' | 'stdio'
  mcpJson: string
  installLabel: string
}

export function buildMcpUrlConfig(baseUrl: string, apiKey = ''): McpUrlConfig {
  const root = String(baseUrl || '').replace(/\/$/, '')
  const cfg: McpUrlConfig = { url: `${root}/api/aiopen/mcp` }
  const key = String(apiKey || '').trim()
  if (key) cfg.headers = { 'X-AIOPEN-Key': key }
  return cfg
}

export function buildMcpRemoteConfig(baseUrl: string, apiKey = ''): McpCommandConfig {
  const root = String(baseUrl || '').replace(/\/$/, '')
  const args = ['-y', 'mcp-remote', `${root}/api/aiopen/mcp`]
  const key = String(apiKey || '').trim()
  if (key) args.push('--header', `X-AIOPEN-Key:${key}`)
  return { command: 'npx', args }
}

export function buildMcpStdioConfig(baseUrl: string, apiKey = '', scriptPath = ''): McpCommandConfig {
  const env: Record<string, string> = { AIOPEN_BASE_URL: String(baseUrl || '').replace(/\/$/, '') }
  const key = String(apiKey || '').trim()
  if (key) env.AIOPEN_API_KEY = key
  return {
    command: 'python3',
    args: [scriptPath || 'FHD/scripts/dev/aiopen_mcp_stdio.py'],
    env,
  }
}

function wrapMcpJson(serverConfig: McpUrlConfig | McpCommandConfig): string {
  return JSON.stringify({ mcpServers: { [AIOPEN_MCP_SERVER_NAME]: serverConfig } }, null, 2)
}

export function buildAiopenClientInstalls(baseUrl: string, apiKey = ''): AiMcpClientInstall[] {
  const urlCfg = buildMcpUrlConfig(baseUrl, apiKey)
  const remoteCfg = buildMcpRemoteConfig(baseUrl, apiKey)

  return [
    {
      id: 'cursor',
      name: 'Cursor',
      icon: '◆',
      configPath: '~/.cursor/mcp.json',
      hint: '复制后粘贴到 ~/.cursor/mcp.json',
      transport: 'url',
      mcpJson: wrapMcpJson(urlCfg),
      installLabel: '复制配置',
    },
    {
      id: 'claude',
      name: 'Claude',
      icon: '✳',
      configPath: 'claude_desktop_config.json',
      hint: '复制后粘贴到 Claude Desktop → 设置 → MCP',
      transport: 'mcp_remote',
      mcpJson: wrapMcpJson(remoteCfg),
      installLabel: '复制配置',
    },
    {
      id: 'vscode',
      name: 'VS Code',
      icon: '▣',
      configPath: 'MCP 扩展 · 用户 settings',
      hint: '复制后粘贴到 VS Code 的 MCP 配置',
      transport: 'mcp_remote',
      mcpJson: wrapMcpJson(remoteCfg),
      installLabel: '复制配置',
    },
    {
      id: 'windsurf',
      name: 'Windsurf',
      icon: '≋',
      configPath: '~/.codeium/windsurf/mcp_config.json',
      hint: '与 Cursor 相同 url 格式，复制后写入配置文件',
      transport: 'url',
      mcpJson: wrapMcpJson(urlCfg),
      installLabel: '复制配置',
    },
    {
      id: 'trae',
      name: 'Trae',
      icon: '◎',
      configPath: 'Trae → MCP 服务器设置',
      hint: '字节 Trae IDE，粘贴 mcpServers JSON',
      transport: 'url',
      mcpJson: wrapMcpJson(urlCfg),
      installLabel: '复制配置',
    },
    {
      id: 'generic',
      name: '其他',
      icon: '⋯',
      configPath: '任意支持 MCP 的 AI 客户端',
      hint: 'Cherry Studio / Chatbox / Open WebUI 等通用 JSON',
      transport: 'mcp_remote',
      mcpJson: wrapMcpJson(remoteCfg),
      installLabel: '复制配置',
    },
  ]
}

export function aiopenInstallStorageKey(clientId: AiMcpClientId): string {
  return `aiopen_installed_${clientId}`
}

export function readAiopenInstalledClients(): AiMcpClientId[] {
  const ids: AiMcpClientId[] = ['cursor', 'claude', 'vscode', 'windsurf', 'trae', 'generic']
  try {
    return ids.filter((id) => localStorage.getItem(aiopenInstallStorageKey(id)) === '1')
  } catch {
    return []
  }
}

export function markAiopenClientInstalled(clientId: AiMcpClientId): void {
  try {
    localStorage.setItem(aiopenInstallStorageKey(clientId), '1')
    localStorage.setItem('aiopen_cursor_installed', '1')
  } catch {
    /* ignore */
  }
}

export function unmarkAiopenClientInstalled(clientId: AiMcpClientId): void {
  try {
    localStorage.removeItem(aiopenInstallStorageKey(clientId))
    if (readAiopenInstalledClients().length === 0) {
      localStorage.removeItem('aiopen_cursor_installed')
    }
  } catch {
    /* ignore */
  }
}

/** 解析 MCP 配置应使用的后端根地址（非 Vite :5001） */
export function resolveAiopenBackendBase(pageOrigin: string, options: { envApiBase?: string; mcpUrl?: string } = {}): string {
  const envBase = String(options.envApiBase || '')
    .trim()
    .replace(/\/$/, '')
  if (envBase && /^https?:\/\//i.test(envBase)) return envBase
  const mcpUrl = String(options.mcpUrl || '').trim()
  if (mcpUrl) {
    try {
      return new URL(mcpUrl).origin
    } catch {
      /* fall through */
    }
  }
  return String(pageOrigin || '').replace(/\/$/, '')
}

/** 单次复制给本地 AI 助手的接入说明及 HTTP 配置。 */
export function buildAiopenOneLiner(
  backendBase: string,
  consoleUrl = '',
  apiKey = '',
): string {
  const base = resolveAiopenBackendBase('', { envApiBase: backendBase })
  const guide = `${base}/api/aiopen/guide?format=markdown`
  // 管理端与主前端入口不同，空屏提示必须给到用户当前所在端的地址
  const screenHint = consoleUrl.trim()
    ? `如果 ui_sessions 为空，请提示我在 ${consoleUrl.trim()} 登录并保持页面打开。`
    : '如果 ui_sessions 为空，请提示我先登录 XCAGI 并保持页面打开。'
  const request = `请用下方 JSON 本地配置 XCAGI AIOPEN MCP（说明 ${guide}），` +
    '依次调用 initialize、tools/list、tools/call ui_sessions，报告连通状态、工具数量和是否有可操控的屏幕。' + screenHint
  return `${request}\n\n\`\`\`json\n${wrapMcpJson(buildMcpUrlConfig(base, apiKey))}\n\`\`\``
}
