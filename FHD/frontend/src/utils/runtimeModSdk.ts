import { apiFetch } from '@/utils/apiBase'

export interface RuntimeModMetadata {
  mod_id: string
  package_version: string
  package_sha256: string
  owner_scope: string
  sdk_version: 1
  entry_url: string
  routes: { path: string; name: string; title: string }[]
  requires_restart: boolean
  runtime_status: string
}

export interface RuntimeModSdk {
  readonly version: 1
  readonly modId: string
  readonly route: Readonly<{ path: string; query: Record<string, unknown> }>
  readonly signal: AbortSignal
  request(path: string, init?: RequestInit): Promise<Response>
  navigate(path: string): Promise<unknown>
}

export interface RuntimeModModule {
  mount(element: HTMLElement, sdk: RuntimeModSdk): (() => void) | Promise<() => void>
}

export function trustedRuntimeEntry(metadata: RuntimeModMetadata): string {
  if (!/^[a-f0-9]{64}$/.test(metadata.package_sha256) || metadata.sdk_version !== 1 || !/^[a-z0-9][a-z0-9_-]{0,95}$/.test(metadata.mod_id)) throw new Error('扩展 SDK 不受支持')
  const prefix = `/api/mods/runtime/${metadata.mod_id}/assets/${metadata.package_sha256}/frontend/runtime/`
  const url = new URL(metadata.entry_url, window.location.origin)
  if (url.origin !== window.location.origin || !url.pathname.startsWith(prefix) || !url.pathname.endsWith('.js') || url.search || url.hash) {
    throw new Error('扩展入口必须来自已验证的本地安装')
  }
  return url.href
}

export async function loadRuntimeMod(metadata: RuntimeModMetadata): Promise<RuntimeModModule> {
  // The server re-verifies the installation, owner and exact file digest before
  // returning these same-origin bytes. No eval, remote loader or CSP exception.
  const entry = trustedRuntimeEntry(metadata)
  const module: RuntimeModModule = await import(/* @vite-ignore */ entry)
  if (typeof module.mount !== 'function') throw new Error('扩展未提供有效的页面入口')
  return module
}

export function createRuntimeModSdk(
  metadata: RuntimeModMetadata,
  route: { path: string; query: Record<string, unknown> },
  signal: AbortSignal,
  navigate: (path: string) => Promise<unknown>,
): RuntimeModSdk {
  const base = `/api/mod/${metadata.mod_id}`
  return Object.freeze({
    version: 1 as const,
    modId: metadata.mod_id,
    route: Object.freeze({ path: route.path, query: Object.freeze({ ...route.query }) }),
    signal,
    request(path: string, init: RequestInit = {}) {
      if (!path.startsWith('/') || path.startsWith('//') || path.includes('..') || path.includes('\\') || /%(?:2e|2f|5c)/i.test(path.split('?')[0] || '')) throw new Error('扩展请求路径无效')
      return apiFetch(`${base}${path}`, { ...init, signal })
    },
    navigate(path: string) {
      if (!path.startsWith(`/mod/${metadata.mod_id}/`) || path.includes('..') || path.includes('\\') || /%(?:2e|2f|5c)/i.test(path.split('?')[0] || '')) throw new Error('扩展导航路径无效')
      return navigate(path)
    },
  })
}
