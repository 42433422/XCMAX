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
      if (current instanceof HTMLElement && (current.scrollTop > 0 || current.scrollLeft > 0)) {
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

  restore(route: string, root: Element | null): void {
    if (!root) return
    for (const position of this.routes.get(route) || []) {
      let target: Element | undefined = root
      for (const index of position.path) {
        target = target?.children.item(index) || undefined
        if (!target) break
      }
      // Content can change across navigation. Never restore to a different node.
      if (!(target instanceof HTMLElement) || target.tagName !== position.tag
        || target.id !== position.id || target.className !== position.className) continue
      target.scrollTop = position.top
      target.scrollLeft = position.left
    }
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
