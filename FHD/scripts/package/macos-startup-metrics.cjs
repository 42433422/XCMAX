function measurement(value, unit, unavailableReason) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return { value, unit, unavailableReason: null }
  }
  return { value: null, unit, unavailableReason }
}

function milestoneMeasurement(value, unit, milestone) {
  if (value === 0) {
    return measurement(
      null,
      unit,
      `${milestone} reported 0; it may not have occurred or may not be exposed for this entry.`,
    )
  }
  return measurement(value, unit, `${milestone} was unavailable in this entry.`)
}

function classifyRequestCategory(entry) {
  let pathname = ''
  try {
    pathname = new URL(String(entry?.name || '')).pathname.toLowerCase()
  } catch {
    return 'other'
  }
  const segments = pathname.split('/').filter(Boolean)
  if (!segments.includes('api')) {
    const initiator = String(entry?.initiatorType || '').toLowerCase()
    return ['script', 'css', 'img', 'font', 'document', 'fetch', 'xmlhttprequest'].includes(initiator)
      ? initiator
      : 'other'
  }
  if (segments.some(segment => segment === 'sku' || segment === 'skus')) return 'sku'
  if (segments.some(segment => segment === 'session' || segment === 'sessions')) return 'session'
  if (segments.at(-1) === 'me') return 'me'
  return 'api-other'
}

function collectStartupTimings({
  mainProcessUptimeSampleSeconds,
  mainProcessUptimeSampleRttMs,
  uiReadyToUptimeSampleMaxDelayMs,
  launchRequestToUiReadySeconds,
  mainProcessTimingError = '',
} = {}) {
  const hasUptime = typeof mainProcessUptimeSampleSeconds === 'number' && Number.isFinite(mainProcessUptimeSampleSeconds)
  const hasUiReadyDelay = typeof uiReadyToUptimeSampleMaxDelayMs === 'number' && Number.isFinite(uiReadyToUptimeSampleMaxDelayMs) && uiReadyToUptimeSampleMaxDelayMs >= 0
  const midpointDelayMs = hasUiReadyDelay ? uiReadyToUptimeSampleMaxDelayMs / 2 : null
  return {
    processStartToUiReadySeconds: measurement(
      hasUptime && hasUiReadyDelay ? Math.max(0, mainProcessUptimeSampleSeconds - midpointDelayMs / 1000) : null,
      'seconds',
      mainProcessTimingError || (!hasUptime
        ? 'Electron main-process uptime sample was not available immediately after UI readiness.'
        : 'The UI-readiness-to-uptime sample delay was unavailable, so no process-start-to-ready estimate was made.'),
    ),
    processUptimeAtSampleSeconds: measurement(
      mainProcessUptimeSampleSeconds,
      'seconds',
      mainProcessTimingError || 'Electron main-process uptime sample was unavailable.',
    ),
    processUptimeSampleDelay: {
      observedRoundTripMs: measurement(
        mainProcessUptimeSampleRttMs,
        'milliseconds',
        'Could not measure the Electron IPC uptime-sample round trip.',
      ),
      possibleDelayRangeMs: hasUiReadyDelay ? { min: 0, max: uiReadyToUptimeSampleMaxDelayMs } : null,
      midpointEstimateMs: midpointDelayMs,
      maximumEstimateErrorMs: midpointDelayMs,
      unavailableReason: hasUiReadyDelay ? null : 'UI-ready-to-uptime sample delay was not observed.',
    },
    launchRequestToUiReadySeconds: measurement(
      launchRequestToUiReadySeconds,
      'seconds',
      'Launch request or UI-ready observation timestamp was unavailable.',
    ),
    nativeWindowFirstFrameSeconds: measurement(
      null,
      'seconds',
      'The packaged runtime exposes no native NSWindow first-frame presentation timestamp; renderer paint timings are not a substitute.',
    ),
  }
}

function collectRendererMetrics(snapshot, snapshotError = '', mainPage = null) {
  const navigation = Array.isArray(snapshot?.navigation) ? snapshot.navigation[0] : null
  const paintEntries = Array.isArray(snapshot?.paint) ? snapshot.paint : []
  const bootstrapEntries = Array.isArray(snapshot?.bootstrapMount) ? snapshot.bootstrapMount : []
  const resources = Array.isArray(snapshot?.resources) ? snapshot.resources : []
  const entryMissing = field => snapshotError || `${field} performance entry was not present in this renderer session.`
  const findPaint = name => paintEntries.find(entry => entry?.name === name)?.startTime

  return {
    mainPage: mainPage || {
      url: null,
      unavailableReason: snapshotError || 'Renderer metrics were not bound to a verified main page.',
    },
    timeOriginEpochMs: measurement(
      snapshot?.timeOriginEpochMs,
      'milliseconds since Unix epoch',
      entryMissing('renderer time origin'),
    ),
    navigation: {
      type: navigation?.type ?? null,
      startTimeMs: measurement(navigation?.startTime, 'milliseconds', entryMissing('navigation start')),
      durationMs: measurement(navigation?.duration, 'milliseconds', entryMissing('navigation duration')),
      requestStartMs: milestoneMeasurement(navigation?.requestStart, 'milliseconds', 'Navigation requestStart'),
      responseStartMs: milestoneMeasurement(navigation?.responseStart, 'milliseconds', 'Navigation responseStart'),
      responseEndMs: milestoneMeasurement(navigation?.responseEnd, 'milliseconds', 'Navigation responseEnd'),
      domInteractiveMs: milestoneMeasurement(navigation?.domInteractive, 'milliseconds', 'Navigation domInteractive'),
      domContentLoadedEventEndMs: milestoneMeasurement(navigation?.domContentLoadedEventEnd, 'milliseconds', 'Navigation domContentLoadedEventEnd'),
      loadEventEndMs: milestoneMeasurement(navigation?.loadEventEnd, 'milliseconds', 'Navigation loadEventEnd'),
    },
    firstPaintMs: measurement(findPaint('first-paint'), 'milliseconds', entryMissing('first-paint')),
    firstContentfulPaintMs: measurement(findPaint('first-contentful-paint'), 'milliseconds', entryMissing('first-contentful-paint')),
    bootstrapMountMs: measurement(bootstrapEntries[0], 'milliseconds', entryMissing('bootstrap_mount mark')),
    requestTimings: {
      count: resources.length,
      entries: resources.map(entry => ({
        category: classifyRequestCategory(entry),
        initiatorType: typeof entry?.initiatorType === 'string' ? entry.initiatorType : null,
        startTimeMs: measurement(entry?.startTime, 'milliseconds', 'Resource start time unavailable.'),
        durationMs: measurement(entry?.duration, 'milliseconds', 'Resource duration unavailable.'),
        requestStartMs: milestoneMeasurement(entry?.requestStart, 'milliseconds', 'Resource requestStart'),
        responseStartMs: milestoneMeasurement(entry?.responseStart, 'milliseconds', 'Resource responseStart'),
        responseEndMs: milestoneMeasurement(entry?.responseEnd, 'milliseconds', 'Resource responseEnd'),
        transferSizeBytes: measurement(entry?.transferSize, 'bytes', 'Resource transfer size unavailable.'),
        encodedBodySizeBytes: measurement(entry?.encodedBodySize, 'bytes', 'Resource encoded body size unavailable.'),
        decodedBodySizeBytes: measurement(entry?.decodedBodySize, 'bytes', 'Resource decoded body size unavailable.'),
      })),
    },
  }
}

module.exports = { classifyRequestCategory, collectRendererMetrics, collectStartupTimings }
