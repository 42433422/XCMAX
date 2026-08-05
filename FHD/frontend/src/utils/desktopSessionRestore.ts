import { validateEnterpriseSessionCached } from '@/utils/authSessionCache'

export type DesktopProfileHydrator = {
  loaded: boolean
  refreshFromServer: () => Promise<void>
}

type DesktopSessionRouter = {
  replace: (location: { name: 'login'; query: { redirect: string } }) => Promise<unknown>
}

let desktopSessionRefreshInFlight: Promise<void> | null = null

/**
 * A prior official validation is enough to render the local shell while a
 * fresh validation happens in the background. API permissions remain enforced
 * server-side; an invalid result immediately returns to the login page.
 */
export function refreshDesktopSessionInBackground(
  router: DesktopSessionRouter,
  profile: DesktopProfileHydrator,
  redirect: string,
): void {
  if (desktopSessionRefreshInFlight) return
  desktopSessionRefreshInFlight = validateEnterpriseSessionCached(true)
    .then(async (valid) => {
      if (!valid) {
        await router.replace({ name: 'login', query: { redirect } })
        return
      }
      await profile.refreshFromServer()
      if (!profile.loaded) {
        await router.replace({ name: 'login', query: { redirect } })
      }
    })
    .catch(() => {
      // Network trouble must not discard a previously working local shell.
      // The next foreground request or navigation revalidates the account.
    })
    .finally(() => {
      desktopSessionRefreshInFlight = null
    })
}
