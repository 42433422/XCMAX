export async function waitForInitialBootstrapDependencies<T>(
  loadI18n: () => Promise<T>,
  waitForInitialRoute: () => Promise<unknown>,
): Promise<T> {
  const [i18n] = await Promise.all([loadI18n(), waitForInitialRoute()])
  return i18n
}
