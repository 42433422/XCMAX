declare module 'mermaid' {
  const mermaid: {
    initialize: (config?: Record<string, unknown>) => void
    run: (options?: Record<string, unknown>) => Promise<void>
    render: (id: string, text: string) => Promise<{ svg: string }>
  }
  export default mermaid
}

declare module '@dagrejs/dagre' {
  const dagre: {
    graphlib: {
      Graph: new () => {
        setDefaultEdgeLabel: (fn: () => Record<string, never>) => void
        setGraph: (config: Record<string, unknown>) => void
        setNode: (id: string, config: Record<string, unknown>) => void
        setEdge: (source: string, target: string) => void
        node: (id: string) => { x: number; y: number } | undefined
      }
    }
    layout: (graph: unknown) => void
  }
  export default dagre
}

declare module '@vue-flow/core' {
  export interface Node {
    id: string
    position?: { x: number; y: number }
    [key: string]: unknown
  }
  export interface Edge {
    id?: string
    source: string
    target: string
    [key: string]: unknown
  }
}
