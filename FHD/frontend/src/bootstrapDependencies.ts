export async function waitForInitialBootstrapDependencies<T>(
  loadI18n: () => Promise<T>,
  waitForInitialRoute: () => Promise<unknown>,
): Promise<T> {
  // A failed first navigation (chunk abort, import error) must not block mount.
  // Authorization redirects resolve isReady(); they are not rejections.
  const [i18n] = await Promise.all([
    loadI18n(),
    waitForInitialRoute().catch(() => undefined),
  ])
  return i18n
}
