/** Guard against the Enter used to commit an IME candidate.
 * Some WebKit/desktop IMEs emit that Enter immediately *after* compositionend,
 * with isComposing=false and keyCode=13. The default must be prevented then.
 */
export const CHAT_IME_ENTER_GUARD_MS = 160

export function createChatComposerImeGuard(now: () => number = () => performance.now()) {
  let composing = false
  let compositionEndedAt = Number.NEGATIVE_INFINITY
  return {
    get composing() { return composing },
    compositionStart() {
      composing = true
      compositionEndedAt = Number.NEGATIVE_INFINITY
    },
    compositionEnd() {
      composing = false
      compositionEndedAt = now()
    },
    shouldSuppressEnter(event: KeyboardEvent): boolean {
      if (composing || event.isComposing || event.keyCode === 229 || event.defaultPrevented) return true
      if (event.key === 'Enter' && now() - compositionEndedAt < CHAT_IME_ENTER_GUARD_MS) {
        // Unlike Enter *during* composition, this can submit a form.
        event.preventDefault()
        return true
      }
      return false
    },
  }
}
