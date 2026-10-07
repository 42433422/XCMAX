const fs = require('node:fs')
const path = require('node:path')
const net = require('node:net')
const http = require('node:http')
const { _electron } = require(path.resolve(__dirname, '../../desktop/node_modules/playwright'))
const [appPath, dataPath, portText, version, sha, evidencePath, packageSha] = process.argv.slice(2)
const port = Number(portText)
const systemIntegration = process.env.XCAGI_ACCEPTANCE_SYSTEM_INTEGRATION === '1'
const result = { scope: 'installed startup only', customerAcceptance: 'pending', finalCandidatePass: false, systemIntegration, version, sha, packageSha, port, dataPath }
const directHealth = () => new Promise((resolve, reject) => {
  const request = http.get({ hostname: '127.0.0.1', port, path: '/api/health', agent: false, timeout: 3000 }, response => {
    let body = ''; response.on('data', chunk => { body += chunk }); response.on('end', () => {
      try { if (response.statusCode !== 200) throw Error(`health HTTP ${response.statusCode}`); resolve(JSON.parse(body)) } catch (error) { reject(error) }
    })
  }); request.on('error', reject); request.on('timeout', () => request.destroy(Error('health timeout')))
})
async function verify() {
  let application
  try {
    if (!appPath || !dataPath || !evidencePath || !Number.isInteger(port) || port < 1024 || port > 65535) throw Error('Invalid isolated launch arguments')
    fs.mkdirSync(evidencePath, { recursive: true }); fs.mkdirSync(dataPath, { recursive: true })
    await new Promise((resolve, reject) => { const server = net.createServer(); server.once('error', reject); server.listen(port, '127.0.0.1', () => server.close(resolve)) })
    const started = Date.now()
    application = await _electron.launch({ executablePath: path.join(fs.realpathSync(appPath), 'Contents/MacOS/XCAGI'), env: { ...process.env, XCAGI_DESKTOP_E2E: systemIntegration ? '0' : '1', XCAGI_DESKTOP_USER_DATA_DIR: fs.realpathSync(dataPath), XCAGI_DESKTOP_PORT: portText }, recordVideo: { dir: path.join(evidencePath, 'videos') }, timeout: 120000 })
    result.pid = application.process().pid
    result.runtime = await application.evaluate(({ app }) => ({ dataPath: app.getPath('userData'), resourcesPath: process.resourcesPath, shellVersion: app.getVersion(), architecture: process.arch }))
    if (result.runtime.dataPath !== fs.realpathSync(dataPath) || result.runtime.resourcesPath !== path.join(fs.realpathSync(appPath), 'Contents/Resources')) throw Error('Installed runtime escaped the selected app or data directory')
    const build = JSON.parse(fs.readFileSync(path.join(result.runtime.resourcesPath, 'build-info.json'), 'utf8'))
    if (build.version !== version || build.gitSha !== sha) throw Error('Installed build identity mismatch')
    let page
    for (let attempt = 0; attempt < 240; attempt += 1) {
      page = application.windows().find(window => window.url().startsWith(`http://127.0.0.1:${port}/login`))
      if (page) break
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    if (!page) throw Error('Installed UI did not reach the login entry')
    await page.getByRole('heading', { name: '企业账号登录', exact: true }).waitFor({ timeout: 30000 })
    await page.getByRole('button', { name: /^登\s*录$/ }).waitFor({ timeout: 30000 })
    result.health = await directHealth()
    if (result.health.version !== version || result.health.git_sha !== sha || result.health.runtime?.status !== 'healthy') throw Error('Packaged backend identity or required runtime readiness mismatch')
    result.ui = { url: page.url(), title: await page.title(), loginVisible: true }
    result.elapsedSeconds = (Date.now() - started) / 1000
    await page.screenshot({ path: path.join(evidencePath, 'installed-login.png') })
    result.startupResult = 'PASS'
  } catch (error) {
    result.startupResult = 'FAIL'; result.error = String(error)
    if (application) for (const [index, window] of application.windows().entries()) {
      await window.screenshot({ path: path.join(evidencePath, `failed-window-${index}.png`) }).catch(() => {})
    }
    process.exitCode = 1
  } finally {
    if (application) await application.close().catch(error => { result.exitError = String(error); process.exitCode = 1 })
    result.finishedAt = new Date().toISOString()
    fs.mkdirSync(evidencePath, { recursive: true })
    fs.writeFileSync(path.join(evidencePath, 'installed-startup.json'), JSON.stringify(result, null, 2))
    console.log(JSON.stringify({ startupResult: result.startupResult, pid: result.pid, port, sha, error: result.error, finalCandidatePass: false }))
  }
}
verify().catch(error => { console.error(error); process.exitCode = 1 })
