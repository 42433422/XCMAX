/** Only the mounted page for this exact route may receive its saved scroll offsets.
 * A Suspense fallback or a leaving page can still occupy the shell during navigation. */
export function findRouteScrollRoot(container: ParentNode, fullPath: string): Element | null {
  const roots = Array.from(container.querySelectorAll('.route-view-shell[data-route-scroll-key]'))
    .filter(root => root.getAttribute('data-route-scroll-key') === fullPath)
  return roots.length === 1 ? roots[0] : null
}

/** Bounded scroll restoration. Scan once when leaving, restore by structural paths.
 * Avoid repeated all-descendant layout reads on every route switch. */
export class RouteScrollMemory {
  private routes = new Map<string, ScrollPosition[]>()
  constructor(private readonly maxRoutes = 24, private readonly maxScrollers = 16) {}

  remember(route: string, root: Element | null): void {
    if (!root || !route) return
    const positions: ScrollPosition[] = []
    const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_ELEMENT)
    let current: Node | null = walker.currentNode
    while (current && positions.length < this.maxScrollers) {
      // Reading scrollTop/Left avoids forcing three separate box measurements
      // for each DOM element, which made large ERP pages slow to leave.
      if (current instanceof HTMLElement && (current.scrollTop !== 0 || current.scrollLeft !== 0)) {
        const path = pathFromRoot(root, current)
        if (path) positions.push({
          path, tag: current.tagName, id: current.id, className: current.className,
          top: current.scrollTop, left: current.scrollLeft,
        })
      }
      current = walker.nextNode()
    }
    this.routes.delete(route)
    if (positions.length) this.routes.set(route, positions)
    while (this.routes.size > this.maxRoutes) {
      const oldest = this.routes.keys().next().value
      if (oldest === undefined) break
      this.routes.delete(oldest)
    }
  }

  restore(route: string, root: Element | null): boolean {
    const positions = this.routes.get(route) || []
    if (!positions.length) return true
    if (!root) return false
    let restored = true
    for (const position of positions) {
      let target: Element | undefined = root
      for (const index of position.path) {
        target = target?.children.item(index) || undefined
        if (!target) break
      }
      // Content can change across navigation. Never restore to a different node.
      if (!(target instanceof HTMLElement) || target.tagName !== position.tag
        || target.id !== position.id || target.className !== position.className) {
        restored = false
        continue
      }
      target.scrollTop = position.top
      target.scrollLeft = position.left
      if (Math.abs(target.scrollTop - position.top) > 1 || Math.abs(target.scrollLeft - position.left) > 1) restored = false
    }
    return restored
  }

  clear(): void { this.routes.clear() }
}

type ScrollPosition = {
  path: number[]
  tag: string
  id: string
  className: string
  top: number
  left: number
}

function pathFromRoot(root: Element, element: Element): number[] | null {
  const path: number[] = []
  let current: Element | null = element
  while (current && current !== root) {
    const parent: Element | null = current.parentElement
    if (!parent) return null
    const index = Array.prototype.indexOf.call(parent.children, current) as number
    if (index < 0) return null
    path.unshift(index)
    current = parent
  }
  return current === root ? path : null
}
