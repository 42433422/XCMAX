const fs = require('node:fs')
const path = require('node:path')
const net = require('node:net')
const http = require('node:http')
const { performance } = require('node:perf_hooks')
const { collectRendererMetrics, collectStartupTimings } = require('./macos-startup-metrics.cjs')
const directHealth = port => new Promise((resolve, reject) => {
  const request = http.get({ hostname: '127.0.0.1', port, path: '/api/health', agent: false, timeout: 3000 }, response => {
    let body = ''; response.on('data', chunk => { body += chunk }); response.on('end', () => {
      try { if (response.statusCode !== 200) throw Error(`health HTTP ${response.statusCode}`); resolve(JSON.parse(body)) } catch (error) { reject(error) }
    })
  }); request.on('error', reject); request.on('timeout', () => request.destroy(Error('health timeout')))
})
const assertPortAvailable = port => new Promise((resolve, reject) => {
  const server = net.createServer()
  server.once('error', reject)
  server.listen(port, '127.0.0.1', () => server.close(resolve))
})
async function verify(args = process.argv.slice(2), adapters = {}) {
  const [appPath, dataPath, portText, version, sha, evidencePath, packageSha] = args
  const port = Number(portText)
  const systemIntegration = process.env.XCAGI_ACCEPTANCE_SYSTEM_INTEGRATION === '1'
  const result = { scope: 'installed startup only', customerAcceptance: 'pending', finalCandidatePass: false, systemIntegration, version, sha, packageSha, port, dataPath }
  result.startupTimings = collectStartupTimings({
    mainProcessTimingError: 'UI readiness was not observed; process-start-to-UI-ready time is unavailable.',
  })
  result.startupTimings.uiReadyCondition = 'Login heading and login button are visible in the installed renderer.'
  result.rendererPerformance = collectRendererMetrics(
    null,
    'UI readiness was not observed; renderer performance entries could not be collected.',
  )
  result.elapsedSeconds = null
  result.elapsedSecondsSemantics = 'Backward-compatible alias for acceptanceVerificationDurationSeconds: launch request through login UI readiness and the health check attempt; not a paint or frame timestamp.'
  result.acceptanceVerificationDurationSeconds = null
  result.acceptanceVerificationDurationUnavailableReason = 'The installed UI and health checks did not both complete.'
  result.elapsedSecondsUnavailableReason = result.acceptanceVerificationDurationUnavailableReason
  let application
  try {
    if (!appPath || !dataPath || !evidencePath || !Number.isInteger(port) || port < 1024 || port > 65535) throw Error('Invalid isolated launch arguments')
    fs.mkdirSync(evidencePath, { recursive: true }); fs.mkdirSync(dataPath, { recursive: true })
    await (adapters.assertPortAvailable || assertPortAvailable)(port)
    const launchElectron = adapters.launchElectron || (options => {
      const { _electron } = require(path.resolve(__dirname, '../../desktop/node_modules/playwright'))
      return _electron.launch(options)
    })
    const launchRequestedAt = performance.now()
    application = await launchElectron({ executablePath: path.join(fs.realpathSync(appPath), 'Contents/MacOS/XCAGI'), env: { ...process.env, XCAGI_DESKTOP_E2E: systemIntegration ? '0' : '1', XCAGI_DESKTOP_USER_DATA_DIR: fs.realpathSync(dataPath), XCAGI_DESKTOP_PORT: portText }, recordVideo: { dir: path.join(evidencePath, 'videos') }, timeout: 120000 })
    result.pid = application.process().pid
    result.runtime = adapters.readRuntime
      ? await adapters.readRuntime(application)
      : await application.evaluate(({ app }) => ({ dataPath: app.getPath('userData'), resourcesPath: process.resourcesPath, shellVersion: app.getVersion(), architecture: process.arch }))
    if (result.runtime.dataPath !== fs.realpathSync(dataPath) || result.runtime.resourcesPath !== path.join(fs.realpathSync(appPath), 'Contents/Resources')) throw Error('Installed runtime escaped the selected app or data directory')
    const build = JSON.parse(fs.readFileSync(path.join(result.runtime.resourcesPath, 'build-info.json'), 'utf8'))
    if (build.version !== version || build.gitSha !== sha) throw Error('Installed build identity mismatch')
    let page
    let mainPageWindowIndex = null
    for (let attempt = 0; attempt < 240; attempt += 1) {
      const windows = application.windows()
      mainPageWindowIndex = windows.findIndex(window => window.url().startsWith(`http://127.0.0.1:${port}/login`))
      page = mainPageWindowIndex >= 0 ? windows[mainPageWindowIndex] : null
      if (page) break
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    if (!page) throw Error('Installed UI did not reach the login entry')
    await page.getByRole('heading', { name: '企业账号登录', exact: true }).waitFor({ timeout: 30000 })
    await page.getByRole('button', { name: /^登\s*录$/ }).waitFor({ timeout: 30000 })
    const uiReadyObservedAt = performance.now()
    let mainProcessUptimeSampleSeconds = null
    let mainProcessTimingError = ''
    let mainProcessUptimeSampleRttMs = null
    let uiReadyToUptimeSampleMaxDelayMs = null
    const uptimeSampleStartedAt = performance.now()
    try {
      const sampleMainProcessUptime = adapters.sampleMainProcessUptime
        ? () => adapters.sampleMainProcessUptime(application)
        : () => application.evaluate(() => process.uptime())
      mainProcessUptimeSampleSeconds = await sampleMainProcessUptime()
    } catch (error) {
      mainProcessTimingError = `main process uptime sample unavailable immediately after UI readiness: ${String(error)}`
    } finally {
      const uptimeSampleReturnedAt = performance.now()
      mainProcessUptimeSampleRttMs = uptimeSampleReturnedAt - uptimeSampleStartedAt
      uiReadyToUptimeSampleMaxDelayMs = uptimeSampleReturnedAt - uiReadyObservedAt
    }
    let rendererSnapshot = null
    let rendererTimingError = ''
    let rendererMainPage = null
    try {
      const currentUrl = new URL(page.url())
      const expectedOrigin = `http://127.0.0.1:${port}`
      if (currentUrl.origin !== expectedOrigin || !/^\/login\/?$/.test(currentUrl.pathname)) {
        throw Error('verified login window URL did not match the selected installed main page')
      }
      rendererMainPage = {
        url: `${currentUrl.origin}${currentUrl.pathname}`,
        windowIndex: mainPageWindowIndex,
        verified: true,
        selection: 'The same window passed the installed login heading and button visibility checks.',
      }
    } catch (error) {
      rendererTimingError = `verified renderer main page unavailable: ${String(error)}`
    }
    if (rendererMainPage) {
      try {
        rendererSnapshot = await page.evaluate(() => ({
          timeOriginEpochMs: performance.timeOrigin,
          navigation: performance.getEntriesByType('navigation').map(entry => ({
            type: entry.type,
            startTime: entry.startTime,
            duration: entry.duration,
            requestStart: entry.requestStart,
            responseStart: entry.responseStart,
            responseEnd: entry.responseEnd,
            domInteractive: entry.domInteractive,
            domContentLoadedEventEnd: entry.domContentLoadedEventEnd,
            loadEventEnd: entry.loadEventEnd,
          })),
          paint: performance.getEntriesByType('paint').map(entry => ({ name: entry.name, startTime: entry.startTime })),
          bootstrapMount: performance.getEntriesByName('bootstrap_mount', 'mark').map(entry => entry.startTime),
          resources: performance.getEntriesByType('resource').map(entry => ({
            // Used only to derive a fixed category; collectRendererMetrics omits URLs.
            name: entry.name,
            initiatorType: entry.initiatorType,
            startTime: entry.startTime,
            duration: entry.duration,
            requestStart: entry.requestStart,
            responseStart: entry.responseStart,
            responseEnd: entry.responseEnd,
            transferSize: entry.transferSize,
            encodedBodySize: entry.encodedBodySize,
            decodedBodySize: entry.decodedBodySize,
          })),
        }))
      } catch (error) {
        rendererTimingError = `renderer performance entries unavailable on verified main page: ${String(error)}`
      }
    }
    result.startupTimings = collectStartupTimings({
      mainProcessUptimeSampleSeconds,
      mainProcessUptimeSampleRttMs,
      uiReadyToUptimeSampleMaxDelayMs,
      launchRequestToUiReadySeconds: (uiReadyObservedAt - launchRequestedAt) / 1000,
      mainProcessTimingError,
    })
    result.startupTimings.uiReadyCondition = 'Login heading and login button are visible in the installed renderer.'
    result.rendererPerformance = collectRendererMetrics(rendererSnapshot, rendererTimingError, rendererMainPage)
    try {
      result.health = await (adapters.healthCheck || directHealth)(port)
    } finally {
      result.acceptanceVerificationDurationSeconds = (performance.now() - launchRequestedAt) / 1000
      result.elapsedSeconds = result.acceptanceVerificationDurationSeconds
      result.acceptanceVerificationDurationUnavailableReason = null
      result.elapsedSecondsUnavailableReason = null
    }
    if (result.health.version !== version || result.health.git_sha !== sha || result.health.runtime?.status !== 'healthy') throw Error('Packaged backend identity or required runtime readiness mismatch')
    result.ui = { url: rendererMainPage?.url || null, title: await page.title(), loginVisible: true }
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
  return result
}

if (require.main === module) {
  verify().catch(error => { console.error(error); process.exitCode = 1 })
}

module.exports = { verify }
