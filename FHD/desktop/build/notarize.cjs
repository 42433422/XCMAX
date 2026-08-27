/**
 * electron-builder afterSign：Developer ID 签名后提交 Apple 公证（notarytool + API Key）。
 */
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

function resolveApiKeyPath() {
  const explicit = (process.env.APP_STORE_CONNECT_API_KEY_PATH || '').trim()
  if (explicit && fs.existsSync(explicit)) return explicit
  const keyId = (process.env.APP_STORE_CONNECT_API_KEY_ID || '').trim()
  const homeP8 = path.join(
    os.homedir(),
    '.appstoreconnect/private_keys',
    `AuthKey_${keyId}.p8`,
  )
  if (keyId && fs.existsSync(homeP8)) return homeP8
  const b64 = (process.env.APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64 || '').trim()
  if (b64 && keyId) {
    const dir = path.join(os.homedir(), '.config/xcagi')
    fs.mkdirSync(dir, { recursive: true })
    const target = path.join(dir, `AuthKey_${keyId}.p8`)
    fs.writeFileSync(target, Buffer.from(b64, 'base64'), { mode: 0o600 })
    return target
  }
  return ''
}

exports.default = async function afterSign(context) {
  if (context.electronPlatformName !== 'darwin') return
  if (process.env.XCAGI_LOCAL_ACCEPTANCE_BUILD === '1') {
    if (process.env.CI) {
      throw new Error('[notarize] XCAGI_LOCAL_ACCEPTANCE_BUILD is forbidden in CI')
    }
    console.log('[notarize] skipped for explicit local acceptance build')
    return
  }

  // @electron/notarize >= 3 is ESM-only. Keep electron-builder's CommonJS
  // afterSign entrypoint, but load the notarization client dynamically.
  const { notarize } = await import('@electron/notarize')

  const appName = context.packager.appInfo.productFilename
  const appPath = `${context.appOutDir}/${appName}.app`
  const apiKeyPath = resolveApiKeyPath()
  const apiKeyId = (process.env.APP_STORE_CONNECT_API_KEY_ID || '').trim()
  const apiIssuer = (process.env.APP_STORE_CONNECT_API_ISSUER_ID || '').trim()
  const appleId = (process.env.APPLE_ID || '').trim()
  const appleIdPassword = (
    process.env.APPLE_APP_SPECIFIC_PASSWORD || process.env.APPLE_ID_PASSWORD || ''
  ).trim()
  const teamId = (process.env.APPLE_TEAM_ID || process.env.IOS_TEAM_ID || '').trim()

  async function withRetry(label, fn, attempts = 3) {
    let lastErr
    for (let i = 1; i <= attempts; i++) {
      try {
        return await fn()
      } catch (err) {
        lastErr = err
        const msg = String(err && err.message ? err.message : err)
        const transient =
          msg.includes('Internet connection appears to be offline') ||
          msg.includes('NSURLErrorDomain Code=-1009') ||
          msg.includes('No network route') ||
          msg.includes('ECONNRESET') ||
          msg.includes('ETIMEDOUT') ||
          msg.includes('ENOTFOUND') ||
          msg.includes('abortedUpload') ||
          msg.includes('deadlineExceeded')
        console.warn(`[notarize] ${label} attempt ${i}/${attempts} failed: ${msg}`)
        if (!transient || i === attempts) throw err
        const waitMs = Math.min(30000, 8000 * i)
        console.warn(`[notarize] retrying in ${waitMs}ms`)
        await new Promise((r) => setTimeout(r, waitMs))
      }
    }
    throw lastErr
  }

  if (apiKeyPath && apiKeyId && apiIssuer) {
    console.log(`[notarize] notarytool via API key for ${appPath}`)
    await withRetry('api-key', () =>
      notarize({
        tool: 'notarytool',
        appPath,
        appleApiKey: apiKeyPath,
        appleApiKeyId: apiKeyId,
        appleApiIssuer: apiIssuer,
      }),
    )
    console.log('[notarize] done (API key)')
    return
  }

  if (appleId && appleIdPassword && teamId) {
    console.log(`[notarize] notarytool via Apple ID for ${appPath}`)
    await withRetry('apple-id', () =>
      notarize({
        tool: 'notarytool',
        appPath,
        appleId,
        appleIdPassword,
        teamId,
      }),
    )
    console.log('[notarize] done (Apple ID)')
    return
  }

  if (process.env.CI) {
    throw new Error(
      '[notarize] CI build requires Apple notarization secrets; set APP_STORE_CONNECT_API_KEY_ID + APP_STORE_CONNECT_API_ISSUER_ID + APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64, or APPLE_ID + APPLE_APP_SPECIFIC_PASSWORD + APPLE_TEAM_ID',
    )
  }
  console.log(
    '[notarize] skipped (local build): set APP_STORE_CONNECT_API_KEY_* or APPLE_ID + APPLE_APP_SPECIFIC_PASSWORD + APPLE_TEAM_ID to enable',
  )
}
