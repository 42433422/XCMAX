const assert = require('node:assert/strict')
const fs = require('node:fs')
const Module = require('node:module')
const http = require('node:http')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')
const { collectRendererMetrics, collectStartupTimings } = require('./macos-startup-metrics.cjs')

test('keeps process, renderer paint, bootstrap mount, and request timing distinct', () => {
  const startup = collectStartupTimings({
    mainProcessUptimeSampleSeconds: 2.75,
    mainProcessUptimeSampleRttMs: 10,
    uiReadyToUptimeSampleMaxDelayMs: 10,
    launchRequestToUiReadySeconds: 3.4,
  })
  const renderer = collectRendererMetrics({
    timeOriginEpochMs: 1_800_000_000_000,
    navigation: [{
      type: 'navigate', startTime: 0, duration: 180, requestStart: 3,
      responseStart: 8, responseEnd: 14, domInteractive: 45,
      domContentLoadedEventEnd: 58, loadEventEnd: 0,
    }],
    paint: [
      { name: 'first-paint', startTime: 26 },
      { name: 'first-contentful-paint', startTime: 39 },
    ],
    bootstrapMount: [74],
    resources: [
      {
        name: 'http://127.0.0.1:5050/api/sku?api_key=never-export-this',
        initiatorType: 'fetch', startTime: 9, duration: 31, requestStart: 11,
        responseStart: 22, responseEnd: 40, transferSize: 1024,
        encodedBodySize: 900, decodedBodySize: 1400,
      },
      {
        name: 'http://127.0.0.1:5050/api/auth/session/volatile-session-id?token=never-export-this',
        initiatorType: 'fetch', startTime: 10, duration: 12, requestStart: 0,
        responseStart: 0, responseEnd: 0, transferSize: 0,
        encodedBodySize: 0, decodedBodySize: 0,
      },
      {
        name: 'http://127.0.0.1:5050/api/me?secret=never-export-this',
        initiatorType: 'fetch', startTime: 11, duration: 13, requestStart: 3,
        responseStart: 5, responseEnd: 6, transferSize: 64,
        encodedBodySize: 50, decodedBodySize: 50,
      },
    ],
  }, '', { url: 'http://127.0.0.1:5050/login', verified: true })

  assert.equal(startup.processStartToUiReadySeconds.value, 2.745)
  assert.equal(startup.processUptimeAtSampleSeconds.value, 2.75)
  assert.deepEqual(startup.processUptimeSampleDelay.possibleDelayRangeMs, { min: 0, max: 10 })
  assert.equal(startup.processUptimeSampleDelay.maximumEstimateErrorMs, 5)
  assert.equal(startup.launchRequestToUiReadySeconds.value, 3.4)
  assert.equal(renderer.mainPage.url, 'http://127.0.0.1:5050/login')
  assert.equal(renderer.navigation.startTimeMs.value, 0)
  assert.equal(renderer.navigation.loadEventEndMs.value, null)
  assert.match(renderer.navigation.loadEventEndMs.unavailableReason, /reported 0/)
  assert.equal(renderer.firstPaintMs.value, 26)
  assert.equal(renderer.firstContentfulPaintMs.value, 39)
  assert.equal(renderer.bootstrapMountMs.value, 74)
  assert.equal(renderer.requestTimings.entries[0].responseStartMs.value, 22)
  assert.deepEqual(renderer.requestTimings.entries.map(entry => entry.category), ['sku', 'session', 'me'])
  assert.equal(renderer.requestTimings.entries[1].requestStartMs.value, null)
  assert.match(renderer.requestTimings.entries[1].requestStartMs.unavailableReason, /reported 0/)
  assert.equal(renderer.requestTimings.entries[1].responseStartMs.value, null)
  assert.equal(renderer.requestTimings.entries[1].responseEndMs.value, null)
  assert.doesNotMatch(JSON.stringify(renderer), /never-export-this|volatile-session-id/)
  assert.equal(startup.nativeWindowFirstFrameSeconds.value, null)
  assert.match(startup.nativeWindowFirstFrameSeconds.unavailableReason, /renderer paint timings are not a substitute/)
  assert.equal(Object.hasOwn(renderer.requestTimings.entries[0], 'url'), false)
})

test('reports absent paint and mount observations as null with field-specific reasons', () => {
  const renderer = collectRendererMetrics({ navigation: [], paint: [], bootstrapMount: [], resources: [] })
  const startup = collectStartupTimings({ mainProcessUptimeSampleSeconds: null })

  assert.equal(renderer.firstPaintMs.value, null)
  assert.match(renderer.firstPaintMs.unavailableReason, /first-paint performance entry/)
  assert.equal(renderer.firstContentfulPaintMs.value, null)
  assert.match(renderer.firstContentfulPaintMs.unavailableReason, /first-contentful-paint performance entry/)
  assert.equal(renderer.bootstrapMountMs.value, null)
  assert.match(renderer.bootstrapMountMs.unavailableReason, /bootstrap_mount mark/)
  assert.equal(renderer.navigation.loadEventEndMs.value, null)
  assert.match(renderer.navigation.loadEventEndMs.unavailableReason, /loadEventEnd/)
  assert.equal(startup.processStartToUiReadySeconds.value, null)
  assert.match(startup.processStartToUiReadySeconds.unavailableReason, /uptime sample was not available/)
  assert.equal(startup.processUptimeSampleDelay.possibleDelayRangeMs, null)
  assert.match(startup.processUptimeSampleDelay.unavailableReason, /UI-ready-to-uptime sample delay/)
  assert.equal(startup.nativeWindowFirstFrameSeconds.value, null)
})

test('records capture failure as missing telemetry rather than a failed UI or substitute metric', () => {
  const renderer = collectRendererMetrics(null, 'renderer inspection unavailable: synthetic offline fixture')

  assert.equal(renderer.firstContentfulPaintMs.value, null)
  assert.equal(renderer.firstContentfulPaintMs.unavailableReason, 'renderer inspection unavailable: synthetic offline fixture')
  assert.equal(renderer.bootstrapMountMs.value, null)
  assert.equal(renderer.requestTimings.count, 0)
  assert.equal(renderer.mainPage.url, null)
  assert.match(renderer.mainPage.unavailableReason, /synthetic offline fixture/)
})

test('importing the launch verifier does not load Playwright or launch a desktop app', () => {
  const originalLoad = Module._load
  Module._load = function (request, parent, isMain) {
    if (String(request).includes('desktop/node_modules/playwright')) {
      throw new Error('Playwright must only load when the verifier runs as a CLI')
    }
    return originalLoad.call(this, request, parent, isMain)
  }
  try {
    const { verify } = require('./verify-macos-launch.cjs')
    assert.equal(typeof verify, 'function')
  } finally {
    Module._load = originalLoad
  }
})

function fakeLaunchCase(t, healthResponse, port = 50123, useDirectHealth = false) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-startup-probe-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  const appPath = path.join(root, 'XCAGI.app')
  const resourcesPath = path.join(appPath, 'Contents', 'Resources')
  const executablePath = path.join(appPath, 'Contents', 'MacOS', 'XCAGI')
  const dataPath = path.join(root, 'isolated-user-data')
  const evidencePath = path.join(root, 'evidence')
  const version = '1.2.3-test'
  const sha = 'a'.repeat(40)
  const packageSha = 'b'.repeat(64)
  fs.mkdirSync(path.dirname(executablePath), { recursive: true })
  fs.mkdirSync(resourcesPath, { recursive: true })
  fs.writeFileSync(executablePath, 'fake executable; never launched')
  fs.writeFileSync(path.join(resourcesPath, 'build-info.json'), JSON.stringify({ version, gitSha: sha }))
  let closed = false
  const page = {
    url: () => `http://127.0.0.1:${port}/login?token=do-not-persist`,
    getByRole: (role, options) => ({
      waitFor: async () => {
        if (role === 'heading') assert.equal(options.name, '企业账号登录')
        if (role === 'button') assert.match(String(options.name), /登/)
      },
    }),
    evaluate: async callback => {
      const snapshot = {
      timeOriginEpochMs: 1_800_000_000_000,
      navigation: [{
        type: 'navigate', startTime: 0, duration: 150, requestStart: 1,
        responseStart: 3, responseEnd: 5, domInteractive: 20,
        domContentLoadedEventEnd: 25, loadEventEnd: 100,
      }],
      paint: [
        { name: 'first-paint', startTime: 15 },
        { name: 'first-contentful-paint', startTime: 19 },
      ],
      bootstrapMount: [31],
      resources: [{
        name: 'http://127.0.0.1:50123/api/auth/me?secret=do-not-persist',
        initiatorType: 'fetch', startTime: 4, duration: 9, requestStart: 5,
        responseStart: 8, responseEnd: 9, transferSize: 12,
        encodedBodySize: 10, decodedBodySize: 10,
      }],
      }
      return require('node:vm').runInNewContext(`(${callback.toString()})()`, {
        performance: {
          timeOrigin: snapshot.timeOriginEpochMs,
          getEntriesByType: type => snapshot[{ navigation: 'navigation', paint: 'paint', resource: 'resources' }[type]],
          getEntriesByName: () => snapshot.bootstrapMount.map(startTime => ({ startTime })),
        },
      })
    },
    title: async () => 'XCAGI Login',
    screenshot: async ({ path: file }) => fs.writeFileSync(file, 'fake screenshot'),
  }
  const application = {
    process: () => ({ pid: 4321 }),
    windows: () => [page],
    close: async () => { closed = true },
  }
  const adapters = {
    assertPortAvailable: async actual => assert.equal(actual, port),
    launchElectron: async options => {
      assert.equal(options.executablePath, path.join(fs.realpathSync(appPath), 'Contents', 'MacOS', 'XCAGI'))
      assert.equal(options.env.XCAGI_DESKTOP_USER_DATA_DIR, fs.realpathSync(dataPath))
      assert.equal(options.env.XCAGI_DESKTOP_PORT, String(port))
      assert.ok(options.recordVideo.dir.endsWith('/videos'))
      return application
    },
    readRuntime: async () => ({
      dataPath: fs.realpathSync(dataPath),
      resourcesPath: fs.realpathSync(resourcesPath),
      shellVersion: version,
      architecture: 'arm64',
    }),
    sampleMainProcessUptime: async () => 3.5,
    healthCheck: async actual => {
      assert.equal(actual, port)
      return healthResponse || { version, git_sha: sha, runtime: { status: 'healthy' } }
    },
  }
  if (useDirectHealth) delete adapters.healthCheck
  const args = [appPath, dataPath, String(port), version, sha, evidencePath, packageSha]
  return { args, adapters, evidencePath, application, get closed() { return closed }, sha, version }
}

async function quietVerify(args, adapters) {
  const originalLog = console.log
  console.log = () => {}
  try {
    const { verify } = require('./verify-macos-launch.cjs')
    return await verify(args, adapters)
  } finally {
    console.log = originalLog
  }
}

test('full verifier success checks app identity, health, UI, timing alias, and isolated data paths', async t => {
  const fixture = fakeLaunchCase(t)
  const result = await quietVerify(fixture.args, fixture.adapters)

  assert.equal(result.startupResult, 'PASS')
  assert.equal(result.runtime.shellVersion, fixture.version)
  assert.equal(result.health.git_sha, fixture.sha)
  assert.equal(result.ui.loginVisible, true)
  assert.equal(result.startupTimings.uiReadyCondition.includes('login button'), true)
  assert.equal(typeof result.startupTimings.processStartToUiReadySeconds.value, 'number')
  assert.ok(result.startupTimings.processUptimeSampleDelay.possibleDelayRangeMs.max >= result.startupTimings.processUptimeSampleDelay.observedRoundTripMs.value)
  assert.equal(result.rendererPerformance.mainPage.url, 'http://127.0.0.1:50123/login')
  assert.equal(result.rendererPerformance.mainPage.windowIndex, 0)
  assert.equal(result.rendererPerformance.requestTimings.entries[0].category, 'me')
  assert.equal(result.elapsedSeconds, result.acceptanceVerificationDurationSeconds)
  assert.equal(typeof result.elapsedSeconds, 'number')
  assert.match(result.elapsedSecondsSemantics, /not a paint or frame timestamp/)
  assert.equal(result.startupTimings.nativeWindowFirstFrameSeconds.value, null)
  assert.equal(fixture.closed, true)
  assert.ok(fs.existsSync(path.join(fixture.evidencePath, 'installed-login.png')))
  const saved = JSON.parse(fs.readFileSync(path.join(fixture.evidencePath, 'installed-startup.json'), 'utf8'))
  assert.equal(saved.elapsedSeconds, saved.acceptanceVerificationDurationSeconds)
  assert.doesNotMatch(JSON.stringify(saved), /do-not-persist/)
})

test('full verifier passes an isolated HTTP health service through directHealth(port)', async t => {
  let healthBody = {}
  const server = http.createServer((request, response) => {
    assert.equal(request.url, '/api/health')
    response.writeHead(200, { 'content-type': 'application/json' })
    response.end(JSON.stringify(healthBody))
  })
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  t.after(() => new Promise(resolve => server.close(resolve)))
  const port = server.address().port
  const fixture = fakeLaunchCase(t, undefined, port, true)
  healthBody = { version: fixture.version, git_sha: fixture.sha, runtime: { status: 'healthy' } }

  const result = await quietVerify(fixture.args, fixture.adapters)
  assert.equal(result.startupResult, 'PASS')
  assert.equal(result.health.git_sha, fixture.sha)
  assert.equal(result.elapsedSeconds, result.acceptanceVerificationDurationSeconds)
})

test('full verifier failure records failed health identity and closes the fake app', async t => {
  const fixture = fakeLaunchCase(t, { version: 'wrong-version', git_sha: 'c'.repeat(40), runtime: { status: 'healthy' } })
  const previousExitCode = process.exitCode
  let result
  try {
    result = await quietVerify(fixture.args, fixture.adapters)
  } finally {
    process.exitCode = previousExitCode
  }

  assert.equal(result.startupResult, 'FAIL')
  assert.match(result.error, /identity or required runtime readiness mismatch/)
  assert.equal(result.elapsedSeconds, result.acceptanceVerificationDurationSeconds)
  assert.equal(typeof result.elapsedSeconds, 'number')
  assert.equal(fixture.closed, true)
  assert.ok(fs.existsSync(path.join(fixture.evidencePath, 'failed-window-0.png')))
  const saved = JSON.parse(fs.readFileSync(path.join(fixture.evidencePath, 'installed-startup.json'), 'utf8'))
  assert.equal(saved.startupResult, 'FAIL')
})
