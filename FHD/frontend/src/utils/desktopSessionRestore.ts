import { captureAuthSession, validateEnterpriseSessionCached } from '@/utils/authSessionCache'

export type DesktopProfileHydrator = {
  loaded: boolean
  sessionCheckUnavailable?: boolean
  refreshFromServer: () => Promise<void>
}

type DesktopSessionRouter = {
  replace: (location: { name: 'login'; query: { redirect: string } }) => Promise<unknown>
}

let desktopSessionRefreshInFlight: Promise<void> | null = null
let refreshOwnerCurrent = () => false

/**
 * A prior official validation is enough to render the local shell while a
 * fresh validation happens in the background. API permissions remain enforced
 * server-side; an invalid result immediately returns to the login page.
 */
export function refreshDesktopSessionInBackground(router: DesktopSessionRouter, profile: DesktopProfileHydrator, redirect: string): void {
  if (desktopSessionRefreshInFlight && refreshOwnerCurrent()) return
  const isCurrent = captureAuthSession()
  refreshOwnerCurrent = isCurrent
  const pending = validateEnterpriseSessionCached(true)
    .then(async (valid) => {
      if (!isCurrent()) return
      if (!valid) {
        await router.replace({ name: 'login', query: { redirect } })
        return
      }
      // validate already returned success. A slow or restarted hydration must not log the user out.
      await profile.refreshFromServer()
    })
    .catch(() => {
      // Network trouble must not discard a previously working local shell.
      // The next foreground request or navigation revalidates the account.
    })
    .finally(() => {
      if (desktopSessionRefreshInFlight === pending) desktopSessionRefreshInFlight = null
    })
  desktopSessionRefreshInFlight = pending
}
