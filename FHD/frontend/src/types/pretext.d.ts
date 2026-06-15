declare module '@chenglou/pretext' {
  export interface LayoutResult {
    width: number;
    height: number;
    lineCount: number;
  }

  export interface LayoutLinesResult {
    width: number;
    height: number;
    lines: Array<{ text: string }>;
  }

  export type LineResult = { text: string };

  export function prepare(
    text: string,
    font: string,
    options?: Record<string, unknown>,
  ): unknown;

  export function layout(
    prepared: unknown,
    width: number,
    lineHeight: number,
  ): LayoutResult;

  export function prepareWithSegments(
    text: string,
    font: string,
    options?: Record<string, unknown>,
  ): unknown;

  export function layoutWithLines(
    prepared: unknown,
    width: number,
    lineHeight: number,
  ): LayoutLinesResult;
}
