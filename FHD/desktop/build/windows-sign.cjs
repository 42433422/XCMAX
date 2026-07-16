const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')

const REQUIRED_ENV = [
  'ES_USERNAME',
  'ES_PASSWORD',
  'CREDENTIAL_ID',
  'ES_TOTP_SECRET',
]

function requireEnv(name) {
  const value = (process.env[name] || '').trim()
  if (!value) {
    throw new Error(`SSL.com eSigner is missing required environment variable: ${name}`)
  }
  return value
}

function resolveCodeSignTool() {
  const toolRoot = (
    process.env.CODE_SIGN_TOOL_PATH || process.env.CODESIGNTOOL_PATH || ''
  ).trim()
  if (!toolRoot) {
    throw new Error(
      'SSL.com CodeSignTool is not installed; run SSLcom/esigner-codesign setup before electron-builder',
    )
  }

  const jar = path.join(toolRoot, 'jar', 'code_sign_tool-1.3.0.jar')
  if (!fs.existsSync(jar)) {
    throw new Error(`SSL.com CodeSignTool jar not found: ${jar}`)
  }

  const javaHome = (process.env.JAVA_HOME || '').trim()
  const java = javaHome
    ? path.join(javaHome, 'bin', process.platform === 'win32' ? 'java.exe' : 'java')
    : 'java'
  if (javaHome && !fs.existsSync(java)) {
    throw new Error(`Java runtime exported by CodeSignTool setup not found: ${java}`)
  }

  return { java, jar }
}

function runCodeSignTool(java, args, file, attempt) {
  const timeoutMs = Number.parseInt(process.env.ES_SIGN_TIMEOUT_MS || '600000', 10)
  return new Promise((resolve, reject) => {
    console.log(
      `[windows-sign] SSL.com eSigner signing ${path.basename(file)} (attempt ${attempt}/3)`,
    )
    const child = spawn(java, args, {
      stdio: ['ignore', 'inherit', 'inherit'],
      windowsHide: true,
    })
    const timer = setTimeout(() => {
      child.kill()
      reject(new Error(`SSL.com CodeSignTool timed out signing ${path.basename(file)}`))
    }, timeoutMs)

    child.once('error', error => {
      clearTimeout(timer)
      reject(error)
    })
    child.once('exit', (code, signal) => {
      clearTimeout(timer)
      if (code === 0) {
        resolve()
        return
      }
      reject(
        new Error(
          `SSL.com CodeSignTool failed for ${path.basename(file)} ` +
            `(exit=${code ?? 'null'}, signal=${signal ?? 'none'})`,
        ),
      )
    })
  })
}

async function sleep(milliseconds) {
  await new Promise(resolve => setTimeout(resolve, milliseconds))
}

exports.default = async function signWithSslCom(configuration) {
  if (process.env.XCAGI_REQUIRE_WINDOWS_SIGNING !== '1') {
    throw new Error('SSL.com signing hook must only run for a signing-required release build')
  }

  for (const name of REQUIRED_ENV) requireEnv(name)
  const { java, jar } = resolveCodeSignTool()
  const file = configuration.path
  if (!file || !fs.existsSync(file)) {
    throw new Error(`electron-builder requested signing for a missing file: ${file || '<empty>'}`)
  }

  const args = [
    '-Xmx1024M',
    '-jar',
    jar,
    'sign',
    `-username=${requireEnv('ES_USERNAME')}`,
    `-password=${requireEnv('ES_PASSWORD')}`,
    `-credential_id=${requireEnv('CREDENTIAL_ID')}`,
    `-totp_secret=${requireEnv('ES_TOTP_SECRET')}`,
    `-input_file_path=${file}`,
    '-override=true',
  ]

  let lastError
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      await runCodeSignTool(java, args, file, attempt)
      return
    } catch (error) {
      lastError = error
      if (attempt < 3) await sleep(attempt * 3000)
    }
  }
  throw lastError
}

exports._test = { REQUIRED_ENV, requireEnv, resolveCodeSignTool }
