#!/usr/bin/env node
/**
 * 桌面端启动时间基线测量脚本
 *
 * 用途：在 Win10/Win11/macOS 上各跑 10 次，区分首次启动 vs 后续启动，
 *      收集 startupMarks（backendSpawnMs / backendHealthMs / desktopStatusMs），
 *      计算 P50/P95，输出 JSON 基线报告供 CI 比对。
 *
 * 用法：
 *   node scripts/measure-startup-baseline.js --runs 10 --mode first-run
 *   node scripts/measure-startup-baseline.js --runs 10 --mode subsequent
 *   node scripts/measure-startup-baseline.js --runs 10 --mode all   # 默认，first + subsequent
 *
 * 输出：
 *   FHD/desktop/metrics/startup-baseline-<platform>-<mode>-<timestamp>.json
 *   控制台打印 P50/P95 摘要表
 *
 * 首次启动 vs 后续启动的区分：
 *   - first-run：启动前清空 userData 目录（含数据库/Mod 种子），模拟用户首次安装
 *   - subsequent：保留 userData 目录，模拟日常使用
 *
 * 启动埋点来源：main.ts 中 `console.info('[xcagi-desktop] startup', JSON.stringify({...startupMarks}))`
 */

const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const ARGS = parseArgs(process.argv.slice(2))
const RUNS = parseInt(ARGS.runs || '10', 10)
const MODE = ARGS.mode || 'all' // first-run | subsequent | all
const APP_BINARY = ARGS.binary || process.env.XCAGI_DESKTOP_BINARY || ''
const USER_DATA_DIR = ARGS.userData || process.env.XCAGI_USER_DATA || path.join(os.tmpdir(), 'xcagi-startup-baseline')

function parseArgs(argv) {
  const out = {}
  for (const arg of argv) {
    const m = arg.match(/^--([^=]+)=(.*)$/)
    if (m) out[m[1]] = m[2]
    else if (arg.startsWith('--no-')) out[arg.slice(5)] = false
    else if (arg.startsWith('--')) out[arg.slice(2)] = true
  }
  return out
}

function percentile(sorted, p) {
  if (sorted.length === 0) return null
  const idx = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)
  return sorted[idx]
}

function stats(values) {
  const sorted = [...values].sort((a, b) => a - b)
  return {
    n: sorted.length,
    min: sorted[0] || null,
    p50: percentile(sorted, 50),
    p95: percentile(sorted, 95),
    max: sorted[sorted.length - 1] || null,
    mean: sorted.length ? Math.round(sorted.reduce((s, x) => s + x, 0) / sorted.length) : null
  }
}

function resolveBinary() {
  if (APP_BINARY && fs.existsSync(APP_BINARY)) return APP_BINARY
  const platform = process.platform
  const repoRoot = path.resolve(__dirname, '..', '..')
  if (platform === 'darwin') {
    const candidates = [
      path.join(repoRoot, 'desktop', 'dist', 'mac-universal', 'XCAGI.app', 'Contents', 'MacOS', 'XCAGI'),
      path.join(repoRoot, 'desktop', 'dist', 'mac', 'XCAGI.app', 'Contents', 'MacOS', 'XCAGI'),
      '/Applications/XCAGI.app/Contents/MacOS/XCAGI'
    ]
    for (const c of candidates) if (fs.existsSync(c)) return c
  } else if (platform === 'win32') {
    const candidates = [
      path.join(repoRoot, 'desktop', 'dist', 'win-unpacked', 'XCAGI.exe'),
      path.join(process.env.PROGRAMFILES || 'C:\\Program Files', 'XCAGI', 'XCAGI.exe')
    ]
    for (const c of candidates) if (fs.existsSync(c)) return c
  }
  throw new Error(`未找到 XCAGI 可执行文件。请用 --binary=<path> 指定，或设置 XCAGI_DESKTOP_BINARY 环境变量。`)
}

/**
 * 启动一次 XCAGI，等待 '[xcagi-desktop] startup' 日志，解析 startupMarks。
 * 超时则失败。
 */
function runOnce({ firstRun, timeoutMs = 240_000 }) {
  if (firstRun) {
    try { fs.rmSync(USER_DATA_DIR, { recursive: true, force: true }) } catch {}
  }
  fs.mkdirSync(USER_DATA_DIR, { recursive: true })

  return new Promise((resolve, reject) => {
    const binary = resolveBinary()
    const child = spawn(binary, [], {
      env: {
        ...process.env,
        XCAGI_DATA_DIR: USER_DATA_DIR,
        // 测量时禁用自动更新检查，避免干扰
        XCAGI_UPDATE_URL: '',
        XCAGI_DESKTOP_PORT: '0' // 让后端自选端口（实际生产是 17500，但测量时避免冲突）
      },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: false
    })

    let stdout = ''
    let stderr = ''
    const startMs = Date.now()
    const timer = setTimeout(() => {
      try { child.kill('SIGTERM') } catch {}
      reject(new Error(`启动超时 ${timeoutMs}ms`))
    }, timeoutMs)

    child.stdout.on('data', chunk => {
      stdout += chunk.toString()
      const lines = stdout.split(/\r?\n/)
      for (const line of lines) {
        if (line.includes('[xcagi-desktop] startup')) {
          clearTimeout(timer)
          const jsonStart = line.indexOf('{')
          const jsonEnd = line.lastIndexOf('}')
          if (jsonStart >= 0 && jsonEnd > jsonStart) {
            try {
              const marks = JSON.parse(line.slice(jsonStart, jsonEnd + 1))
              const totalMs = Date.now() - startMs
              try { child.kill('SIGTERM') } catch {}
              resolve({ marks, totalMs, raw: line })
              return
            } catch (e) {
              // 解析失败，继续等
            }
          }
        }
      }
    })
    child.stderr.on('data', chunk => { stderr += chunk.toString() })
    child.on('exit', code => {
      clearTimeout(timer)
      if (code !== 0 && code !== null && !stdout.includes('[xcagi-desktop] startup')) {
        reject(new Error(`进程异常退出 code=${code}\nstderr: ${stderr.slice(-500)}`))
      }
    })
    child.on('error', err => {
      clearTimeout(timer)
      reject(err)
    })
  })
}

async function runBatch({ firstRun, runs }) {
  const results = []
  for (let i = 0; i < runs; i++) {
    process.stdout.write(`  [${i + 1}/${runs}] ${firstRun ? 'first-run' : 'subsequent'}... `)
    try {
      const r = await runOnce({ firstRun })
      process.stdout.write(`OK total=${r.totalMs}ms health=${r.marks.backendHealthMs ?? 'n/a'}ms\n`)
      results.push(r)
    } catch (e) {
      process.stdout.write(`FAIL ${e.message}\n`)
      results.push({ error: e.message, marks: null, totalMs: null })
    }
    // 间歇，避免端口/文件锁竞争
    await new Promise(r => setTimeout(r, 2000))
  }
  return results
}

function summarize(results) {
  const valid = results.filter(r => r.marks && typeof r.totalMs === 'number')
  return {
    totalRuns: results.length,
    successfulRuns: valid.length,
    failedRuns: results.length - valid.length,
    totalMs: stats(valid.map(r => r.totalMs)),
    backendHealthMs: stats(valid.map(r => r.marks.backendHealthMs).filter(x => typeof x === 'number')),
    desktopStatusMs: stats(valid.map(r => r.marks.desktopStatusMs).filter(x => typeof x === 'number'))
  }
}

async function main() {
  const platform = process.platform
  const platformLabel = platform === 'darwin' ? 'mac' : platform === 'win32' ? 'win' : platform
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
  console.log(`\n=== XCAGI 桌面端启动时间基线测量 ===`)
  console.log(`平台: ${platformLabel}, 运行次数: ${RUNS}, 模式: ${MODE}`)
  console.log(`userData 目录: ${USER_DATA_DIR}\n`)

  const metricsDir = path.resolve(__dirname, '..', 'metrics')
  fs.mkdirSync(metricsDir, { recursive: true })

  const report = {
    platform: platformLabel,
    arch: process.arch,
    nodeVersion: process.version,
    timestamp: new Date().toISOString(),
    runs: RUNS,
    mode: MODE,
    samples: { firstRun: [], subsequent: [] },
    summary: { firstRun: null, subsequent: null }
  }

  if (MODE === 'first-run' || MODE === 'all') {
    console.log(`\n--- 首次启动（清空 userData） ---`)
    report.samples.firstRun = await runBatch({ firstRun: true, runs: RUNS })
    report.summary.firstRun = summarize(report.samples.firstRun)
  }
  if (MODE === 'subsequent' || MODE === 'all') {
    console.log(`\n--- 后续启动（保留 userData） ---`)
    report.samples.subsequent = await runBatch({ firstRun: false, runs: RUNS })
    report.summary.subsequent = summarize(report.samples.subsequent)
  }

  const outFile = path.join(metricsDir, `startup-baseline-${platformLabel}-${timestamp}.json`)
  fs.writeFileSync(outFile, JSON.stringify(report, null, 2), 'utf8')

  console.log(`\n=== 摘要 ===`)
  if (report.summary.firstRun) {
    const s = report.summary.firstRun
    console.log(`首次启动   total P50=${s.totalMs.p50}ms P95=${s.totalMs.p95}ms | health P95=${s.backendHealthMs.p95 ?? 'n/a'}ms (n=${s.successfulRuns})`)
  }
  if (report.summary.subsequent) {
    const s = report.summary.subsequent
    console.log(`后续启动   total P50=${s.totalMs.p50}ms P95=${s.totalMs.p95}ms | health P95=${s.backendHealthMs.p95 ?? 'n/a'}ms (n=${s.successfulRuns})`)
  }
  console.log(`\n基线报告已写入: ${outFile}`)

  // 阈值检查（可选，通过环境变量配置）
  const thresholdTotalP95 = parseInt(process.env.XCAGI_STARTUP_TOTAL_P95_MS || '0', 10)
  if (thresholdTotalP95 > 0 && report.summary.subsequent) {
    const actualP95 = report.summary.subsequent.totalMs.p95
    if (actualP95 && actualP95 > thresholdTotalP95) {
      console.error(`\n❌ 阈值检查失败：后续启动 P95=${actualP95}ms > 阈值 ${thresholdTotalP95}ms`)
      process.exit(1)
    } else {
      console.log(`\n✅ 阈值检查通过：后续启动 P95=${actualP95}ms ≤ 阈值 ${thresholdTotalP95}ms`)
    }
  }
}

main().catch(e => {
  console.error('FATAL:', e)
  process.exit(1)
})
