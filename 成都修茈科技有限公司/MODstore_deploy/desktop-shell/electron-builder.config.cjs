const requiredSigningVars = [
  'AZURE_TENANT_ID',
  'AZURE_CLIENT_ID',
  'AZURE_CLIENT_SECRET',
  'AZURE_TRUSTED_SIGNING_ENDPOINT',
  'AZURE_TRUSTED_SIGNING_ACCOUNT',
  'AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE',
]

const missingSigningVars = requiredSigningVars.filter((name) => !process.env[name])
const requireSigning = process.env.XCAGI_REQUIRE_WINDOWS_SIGNING === '1'

if (requireSigning && missingSigningVars.length) {
  throw new Error(`Windows signing required, but missing: ${missingSigningVars.join(', ')}`)
}

const publisherName = process.env.XCAGI_WINDOWS_PUBLISHER_NAME || '成都修茈科技有限公司'

const azureSignOptions = missingSigningVars.length
  ? undefined
  : {
      endpoint: process.env.AZURE_TRUSTED_SIGNING_ENDPOINT,
      codeSigningAccountName: process.env.AZURE_TRUSTED_SIGNING_ACCOUNT,
      certificateProfileName: process.env.AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE,
      publisherName,
    }

const productSku = process.env.XCAGI_PRODUCT_SKU === 'enterprise' ? 'enterprise' : 'personal'
const productLabel = productSku === 'enterprise' ? 'Enterprise' : 'Personal'

/** @type {import('electron-builder').Configuration} */
module.exports = {
  appId: 'com.xiuci.xcagi.desktop',
  productName: 'XCAGI',
  artifactName: `XCAGI-${productLabel}-Setup-\${version}-\${arch}.\${ext}`,
  publish: [{ provider: 'generic', url: `https://xiu-ci.com/xcagi-v10.0.0/${productSku}/` }],
  directories: { output: 'dist' },
  files: ['main.js', 'preload.js', 'package.json'],
  win: {
    target: [{ target: 'nsis', arch: ['x64'] }],
    requestedExecutionLevel: 'asInvoker',
    ...(azureSignOptions ? { azureSignOptions } : {}),
  },
  nsis: {
    oneClick: false,
    perMachine: false,
    allowElevation: false,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: 'XCAGI',
  },
}
