/**
 * electron-builder afterSign 钩子。
 *
 * 当前 electron-builder.yml 中 mac.notarize = false，因此此处不执行 Apple 公证。
 * 保留钩子以满足 afterSign 配置引用，避免 electron-builder 因找不到模块而失败。
 *
 * 未来启用公证时，在此处调用 @electron/notarize（已在 devDependencies 中）:
 *
 *   const { notarize } = require('@electron/notarize')
 *   exports.default = async function afterSign(context) {
 *     const { appOutDir, electronPlatformName } = context
 *     if (electronPlatformName !== 'darwin') return
 *     const appName = context.packager.appInfo.productFilename
 *     await notarize({
 *       appBundleId: context.packager.appInfo.id,
 *       appPath: `${appOutDir}/${appName}.app`,
 *       appleId: process.env.APPLE_ID,
 *       appleIdPassword: process.env.APPLE_APP_SPECIFIC_PASSWORD,
 *       teamId: process.env.APPLE_TEAM_ID
 *     })
 *   }
 */
exports.default = async function afterSign(context) {
  // notarize: false — 当前无操作。
  // 保留 context 参数以匹配 electron-builder 钩子签名。
  void context
}
