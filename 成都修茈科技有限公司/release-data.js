/* Shared read-only projection of release-managed pointers; never infer publication from history. */
;(function (root) {
  'use strict'
  var origin = 'https://xiu-ci.com'
  var versionPattern = /^\d+(?:\.\d+){2,3}$/
  var commitPattern = /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/i
  function fetchJson(url) {
    return fetch(url, { cache: 'no-store' }).then(function (response) {
      return response.ok && (response.headers.get('content-type') || '').includes('json') ? response.json() : null
    }).catch(function () { return null })
  }
  function history(rows) {
    var seen = new Set()
    return (Array.isArray(rows) ? rows : []).filter(function (row) {
      if (!row || typeof row.version !== 'string' || !row.version.trim()) return false
      var key = String(row.product || 'XCAGI') + ':' + row.version.trim().replace(/^v/, '')
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }
  function manifestUrl(pointer) {
    if (!pointer || !versionPattern.test(pointer.download_version || '')) return ''
    var base = pointer.release_root || pointer.cos_base_url || origin + '/xcagi-v' + pointer.download_version
    var url = pointer.manifest_url || (typeof base === 'string' ? base.replace(/\/$/, '') + '/manifest.json' : '')
    return typeof url === 'string' && url.startsWith(origin + '/') ? url : ''
  }
  function view(pointer, manifest, hotfix) {
    pointer = pointer || {}
    var version = versionPattern.test(pointer.download_version || '') && (!pointer.version_lock || pointer.version_lock === pointer.download_version) ? pointer.download_version : ''
    var androidVersion = versionPattern.test(pointer.android_version || '') ? pointer.android_version : ''
    var base = origin + '/xcagi-v' + version
    function filename(platform, arch) {
      if (platform === 'android') return 'XCAGI-Enterprise-Android-' + androidVersion + '.apk'
      if (platform === 'mac') return 'XCAGI-Enterprise-' + version + '-mac-' + arch + '.dmg'
      return 'XCAGI-Enterprise-Setup-' + version + '-x64.exe'
    }
    function intact(artifact) {
      return artifact && /^[a-f0-9]{64}$/i.test(artifact.sha256 || '') && Number.isSafeInteger(artifact.size) && artifact.size > 0
    }
    function interim() {
      var artifact = hotfix && hotfix.artifact
      var testRelease = hotfix && hotfix.release && hotfix.release.test_only === true
      var disclosed = testRelease && hotfix.release.version === hotfix.version && Array.isArray(hotfix.release.notes) && hotfix.release.notes.length && hotfix.release.notes.every(function (note) { return typeof note === 'string' && note.trim() })
      if (!intact(artifact) || hotfix.schema !== 'xcagi.windows_interim_release/v1' || !versionPattern.test(hotfix.version || '') ||
        (testRelease ? !disclosed : !version || hotfix.version !== version)) return null
      var base = origin + '/xcagi-v' + hotfix.version
      var status = hotfix.signature_status
      var name = 'XCAGI-Enterprise-Setup-' + hotfix.version + '-x64-' + status + '.exe'
      var accepted = status === 'unsigned' && hotfix.risk_acceptance && Date.parse(hotfix.risk_acceptance.expires_at) > Date.now()
      if (hotfix.download_allowed !== true || hotfix.stable_auto_update !== false || (status !== 'signed' && !accepted) ||
        !commitPattern.test(hotfix.git_sha || '') || artifact.platform !== 'windows' || artifact.arch !== 'x64' || artifact.filename !== name ||
        artifact.url !== base + '/enterprise/' + hotfix.git_sha + '/' + artifact.sha256 + '/' + name) return null
      return hotfix
    }
    function entry(platform, arch) {
      var sku = manifest && manifest.channels && manifest.channels.official_download && manifest.channels.official_download.enterprise
      if (!version || !sku || manifest.schema !== 'xcagi.download_manifest/v1' || pointer.release_ready !== true || manifest.release_ready !== true ||
        manifest.version !== version || !commitPattern.test(pointer.git_sha || '') || manifest.git_sha !== pointer.git_sha ||
        !pointer.release_id || manifest.release_id !== pointer.release_id) return null
      var name = filename(platform, arch)
      var artifact = platform === 'mac' ? (Array.isArray(sku.mac) ? sku.mac : []).find(function (row) { return row && row.filename === name }) : sku[platform]
      var validUrl = artifact && (artifact.url === base + '/enterprise/' + name || (platform === 'mac' &&
        artifact.url === base + '/builds/' + pointer.git_sha + '/enterprise/' + name))
      return intact(artifact) && artifact.filename === name && validUrl && (platform !== 'android' || androidVersion) &&
        (!artifact.arch || artifact.arch === (platform === 'mac' ? arch : platform === 'win' ? 'x64' : artifact.arch)) ? artifact : null
    }
    function platform(platform, arch) {
      var temporary = platform === 'win' ? interim() : null
      var artifact = temporary ? temporary.artifact : entry(platform, arch)
      return { artifact: artifact, version: temporary ? temporary.version : platform === 'android' ? androidVersion : version,
        channel: platform === 'android' ? '实验版·非签约级' : temporary ? (temporary.release && temporary.release.test_only ? '测试版·手动下载·不进入自动更新' : '临时手动下载·不进入自动更新') : '手动下载·自动更新状态未核实',
        status: artifact ? '可下载' : '未开放（制品清单缺失、未就绪或身份不一致）', temporary: temporary }
    }
    return { version: version, androidVersion: androidVersion, filename: filename, entry: entry, interim: interim, platform: platform }
  }
  root.XCReleaseData = { fetchJson: fetchJson, history: history, manifestUrl: manifestUrl, view: view }
})(typeof window === 'undefined' ? globalThis : window)
