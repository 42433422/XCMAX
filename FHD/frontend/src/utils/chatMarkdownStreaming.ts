/** Only defer rich Markdown while a reply is still growing.
 * DOMPurify/Markdown parsing are linear in the full document and should not
 * run repeatedly for very long replies. The final display uses the original
 * source and the normal sanitization pipeline without truncating content.
 */
export const LONG_STREAM_MARKDOWN_THRESHOLD = 16_384

export function shouldDeferMarkdownWhileStreaming(content: string, streaming: boolean): boolean {
  return streaming && content.length > LONG_STREAM_MARKDOWN_THRESHOLD
}
