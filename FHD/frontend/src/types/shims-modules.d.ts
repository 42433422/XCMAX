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
  import type { Component } from 'vue'
  export interface Node {
    id: string
    type?: string
    position?: { x: number; y: number }
    data?: Record<string, unknown>
    [key: string]: unknown
  }
  export interface Edge {
    id?: string
    source: string
    target: string
    [key: string]: unknown
  }
  export const VueFlow: Component
  export function useVueFlow(...args: unknown[]): {
    fitView: (opts?: Record<string, unknown>) => void
    [key: string]: unknown
  }
}

declare module 'xlsx' {
  export interface WorkBook {
    SheetNames: string[]
    Sheets: Record<string, unknown>
  }
  export function read(data: ArrayBuffer | string, opts?: Record<string, unknown>): WorkBook
  export function write(workbook: WorkBook, opts?: Record<string, unknown>): ArrayBuffer | Uint8Array | string
  export const utils: {
    sheet_to_json: (sheet: unknown, opts?: Record<string, unknown>) => unknown[][]
    book_new: () => WorkBook
    book_append_sheet: (workbook: WorkBook, sheet: unknown, name?: string) => void
    aoa_to_sheet: (data: unknown[][]) => unknown
    json_to_sheet: (data: Record<string, unknown>[]) => unknown
  }
}
