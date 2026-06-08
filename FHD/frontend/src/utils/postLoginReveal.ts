export const POST_LOGIN_REVEAL_KEY = 'xcagi.postLoginReveal'

export function armPostLoginReveal(): void {
  try {
    sessionStorage.setItem(POST_LOGIN_REVEAL_KEY, '1')
  } catch {
    /* ignore */
  }
}

export function consumePostLoginReveal(): boolean {
  try {
    if (sessionStorage.getItem(POST_LOGIN_REVEAL_KEY) !== '1') return false
    sessionStorage.removeItem(POST_LOGIN_REVEAL_KEY)
    return true
  } catch {
    return false
  }
}
