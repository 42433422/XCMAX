export interface VirtualCursorMoveOptions {
  duration?: number
  click?: boolean
  label?: string
}

export interface VirtualCursorClickOptions {
  duration?: number
  label?: string
}

export interface VirtualCursorApi {
  moveTo(
    target: HTMLElement | { x: number; y: number },
    options?: VirtualCursorMoveOptions,
  ): void
  click(target: HTMLElement, options?: VirtualCursorClickOptions): void
  hide(): void
  show(): void
}

declare global {
  interface Window {
    virtualCursor?: VirtualCursorApi
  }
}

export {}
