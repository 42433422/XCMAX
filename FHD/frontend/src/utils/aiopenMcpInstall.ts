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
  /** 一键安装：deeplink / web / vscode */
  installUrl?: string
  installFallbackUrl?: string
  installMode: 'deeplink' | 'vscode' | 'copy'
  installLabel: string
}

function toBase64Json(obj: unknown): string {
  const json = JSON.stringify(obj)
  return btoa(unescape(encodeURIComponent(json)))
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

export function buildCursorDeeplink(serverName: string, serverConfig: McpUrlConfig | McpCommandConfig): string {
  const configB64 = toBase64Json(serverConfig)
  return `cursor://anysphere.cursor-deeplink/mcp/install?name=${encodeURIComponent(serverName)}&config=${encodeURIComponent(configB64)}`
}

export function buildCursorWebInstallUrl(serverName: string, serverConfig: McpUrlConfig | McpCommandConfig): string {
  const configB64 = toBase64Json(serverConfig)
  return `https://cursor.com/en/install-mcp?name=${encodeURIComponent(serverName)}&config=${encodeURIComponent(configB64)}`
}

/** VS Code MCP 扩展一键安装 */
export function buildVsCodeInstallUrl(serverName: string, serverConfig: McpCommandConfig): string {
  const payload = JSON.stringify({ name: serverName, ...serverConfig })
  return `vscode://mcp/install?${encodeURIComponent(payload)}`
}

/** @deprecated 使用 buildAiopenClientInstalls */
export function buildAiopenCursorInstallLinks(baseUrl: string, apiKey = '') {
  const config = buildMcpUrlConfig(baseUrl, apiKey)
  return {
    config,
    deeplink: buildCursorDeeplink(AIOPEN_MCP_SERVER_NAME, config),
    webUrl: buildCursorWebInstallUrl(AIOPEN_MCP_SERVER_NAME, config),
    mcpJson: wrapMcpJson(config),
  }
}

export function buildAiopenClientInstalls(
  baseUrl: string,
  apiKey = '',
  options: { stdioScriptPath?: string } = {}
): AiMcpClientInstall[] {
  const urlCfg = buildMcpUrlConfig(baseUrl, apiKey)
  const remoteCfg = buildMcpRemoteConfig(baseUrl, apiKey)
  const stdioCfg = buildMcpStdioConfig(baseUrl, apiKey, options.stdioScriptPath)

  return [
    {
      id: 'cursor',
      name: 'Cursor',
      icon: '◆',
      configPath: '~/.cursor/mcp.json',
      hint: '点一下自动写入 MCP 配置',
      transport: 'url',
      mcpJson: wrapMcpJson(urlCfg),
      installUrl: buildCursorDeeplink(AIOPEN_MCP_SERVER_NAME, urlCfg),
      installFallbackUrl: buildCursorWebInstallUrl(AIOPEN_MCP_SERVER_NAME, urlCfg),
      installMode: 'deeplink',
      installLabel: '一键安装',
    },
    {
      id: 'claude',
      name: 'Claude',
      icon: '✳',
      configPath: 'claude_desktop_config.json',
      hint: '复制后粘贴到 Claude Desktop → 设置 → MCP',
      transport: 'mcp_remote',
      mcpJson: wrapMcpJson(remoteCfg),
      installMode: 'copy',
      installLabel: '复制配置',
    },
    {
      id: 'vscode',
      name: 'VS Code',
      icon: '▣',
      configPath: 'MCP 扩展 · 用户 settings',
      hint: '需安装 MCP 扩展；也可复制 JSON 手动添加',
      transport: 'mcp_remote',
      mcpJson: wrapMcpJson(remoteCfg),
      installUrl: buildVsCodeInstallUrl(AIOPEN_MCP_SERVER_NAME, remoteCfg),
      installMode: 'vscode',
      installLabel: '一键安装',
    },
    {
      id: 'windsurf',
      name: 'Windsurf',
      icon: '≋',
      configPath: '~/.codeium/windsurf/mcp_config.json',
      hint: '与 Cursor 相同 url 格式，复制后写入配置文件',
      transport: 'url',
      mcpJson: wrapMcpJson(urlCfg),
      installMode: 'copy',
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
      installMode: 'copy',
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
      installMode: 'copy',
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
export function resolveAiopenBackendBase(
  pageOrigin: string,
  options: { envApiBase?: string; mcpUrl?: string } = {}
): string {
  const envBase = String(options.envApiBase || '').trim().replace(/\/$/, '')
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

/** 一句话话术（粘贴给 ChatGPT / Claude 网页版等） */
export function buildAiopenOneLiner(backendBase: string, apiKey = ''): string {
  const base = resolveAiopenBackendBase('', { envApiBase: backendBase })
  const guide = `${base}/api/aiopen/guide?format=markdown`
  const keyHint = apiKey.trim()
    ? `连接口令是 ${apiKey.trim()}，`
    : ''
  return `请打开 ${guide} 阅读 XCAGI AIOPEN 接入说明，${keyHint}帮我写好 MCP 配置并验证连通，完成后告诉我能否操控本软件。`
}

/** 生成可粘贴给任意 AI 助手（ChatGPT / Claude / Kimi 等）的配置提示语 */
export function buildAiAssistantSetupPrompt(options: {
  backendBase: string
  apiKey?: string
  clientId?: AiMcpClientId
  guideUrl?: string
}): string {
  const base = resolveAiopenBackendBase('', { envApiBase: options.backendBase })
  const guide = options.guideUrl || `${base}/api/aiopen/guide?format=markdown`
  const clients = buildAiopenClientInstalls(base, options.apiKey || '')
  const client =
    clients.find((c) => c.id === (options.clientId || 'generic')) || clients[clients.length - 1]
  const keyLine = options.apiKey?.trim()
    ? `- 连接口令（请求头 X-AIOPEN-Key）：${options.apiKey.trim()}`
    : '- 连接口令：开发模式可留空'

  return `请帮我接入 XCAGI AIOPEN（MCP 开放平台），完成后告诉我是否配置成功。

## 请你执行
1. 打开并阅读接入说明：${guide}
2. 将下方 JSON 写入我的 **${client.name}**（${client.configPath}）
3. 验证 MCP：initialize → tools/list（应有 9 个工具）→ tools/call name=ui_sessions

## MCP 配置（${client.name}）
\`\`\`json
${client.mcpJson}
\`\`\`

## 服务端信息
- MCP 端点：${base}/api/aiopen/mcp
- REST 调用：${base}/api/aiopen/invoke
${keyLine}

## 完成后请告诉我
- MCP 是否连通、tools/list 工具数量
- 是否检测到 ui_sessions（我已在浏览器打开 AIOPEN 并开启待命）
- 我可以说「帮我查订单 / 打开产品页」让你通过虚拟光标操控软件`
}
