import type { AminEmployeePlugin } from '@amin/_types'

const modules = import.meta.glob<{ default: AminEmployeePlugin }>('@amin/*/register.ts', { eager: true })

const _plugins: AminEmployeePlugin[] = []

for (const [path, mod] of Object.entries(modules)) {
  if (mod?.default) {
    _plugins.push(mod.default)
  }
}

_plugins.sort((a, b) => {
  const kindOrder: Record<string, number> = { core: 0, fixed_extension: 1, extension: 2 }
  return (kindOrder[a.kind] ?? 9) - (kindOrder[b.kind] ?? 9)
})

export const aminPlugins: ReadonlyArray<AminEmployeePlugin> = Object.freeze([..._plugins])

export function aminPluginIds(): string[] {
  return aminPlugins.map((p) => p.id)
}

export function aminPluginById(id: string): AminEmployeePlugin | undefined {
  return aminPlugins.find((p) => p.id === id)
}

export function aminCorePluginIds(): string[] {
  return aminPlugins.filter((p) => p.kind === 'core').map((p) => p.id)
}

export function aminFixedExtensionPluginIds(): string[] {
  return aminPlugins.filter((p) => p.kind === 'fixed_extension').map((p) => p.id)
}

export function aminDefaultEnabledMap(): Record<string, boolean> {
  const out: Record<string, boolean> = {}
  for (const p of aminPlugins) {
    out[p.id] = p.defaultEnabled ?? false
  }
  return out
}

export function aminPanelTitleMap(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const p of aminPlugins) {
    if (p.panelTitle) out[p.id] = p.panelTitle
  }
  return out
}

export function aminDatabaseLinkMap(): Record<string, { routeName: string; label: string; description: string }> {
  const out: Record<string, { routeName: string; label: string; description: string }> = {}
  for (const p of aminPlugins) {
    if (p.databaseLink) out[p.id] = p.databaseLink
  }
  return out
}

export function aminStitchPlacements(): Array<{ empId: string; leftPct: number; topPct: number; scale?: number }> {
  return aminPlugins
    .filter((p) => p.stitchPlacement)
    .map((p) => ({ empId: p.id, ...p.stitchPlacement! }))
}

export function aminFlowDocMap(): Record<string, AminEmployeePlugin['flowDoc']> {
  const out: Record<string, AminEmployeePlugin['flowDoc']> = {}
  for (const p of aminPlugins) {
    if (p.flowDoc) out[p.id] = p.flowDoc
  }
  return out
}

export function aminSignalBridges(): Array<{ empId: string; eventNames: string[]; handler: (detail: Record<string, unknown>) => void }> {
  const out: Array<{ empId: string; eventNames: string[]; handler: (detail: Record<string, unknown>) => void }> = []
  for (const p of aminPlugins) {
    if (p.signalBridges) {
      for (const bridge of p.signalBridges) {
        out.push({ empId: p.id, eventNames: bridge.eventNames, handler: bridge.handler })
      }
    }
  }
  return out
}
