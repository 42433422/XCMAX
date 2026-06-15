/**
 * Optional macOS notarization hook for electron-builder afterSign.
 * Skips when APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD are unset (CI smoke, local dev).
 */
exports.default = async function notarizeAfterSign(context) {
  if (context.electronPlatformName !== 'darwin') {
    return;
  }
  const appleId = process.env.APPLE_ID;
  const appleIdPassword = process.env.APPLE_APP_SPECIFIC_PASSWORD;
  const teamId = process.env.APPLE_TEAM_ID;
  if (!appleId || !appleIdPassword || !teamId) {
    console.warn('[notarize] Skipping: APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID not set');
    return;
  }
  const { notarize } = await import('@electron/notarize');
  const appName = context.packager.appInfo.productFilename;
  const appPath = `${context.appOutDir}/${appName}.app`;
  await notarize({
    appBundleId: context.packager.appInfo.id,
    appPath,
    appleId,
    appleIdPassword,
    teamId,
  });
};
