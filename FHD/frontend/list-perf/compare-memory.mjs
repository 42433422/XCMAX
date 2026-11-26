import fs from 'node:fs'
import path from 'node:path'

const root = process.argv[2]
if (!root) throw new Error('Usage: node compare-memory.mjs <UI_PERF_ROOT>')

function locate(dir, name) {
  if (!fs.existsSync(dir)) return null
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      const nested = locate(file, name)
      if (nested) return nested
    } else if (entry.name === name) return file
  }
  return null
}
function read(side) {
  const file = locate(path.join(root, side, 'long-list'), 'memory-curve.json')
  if (!file) throw new Error(side + ': measured memory-curve.json is missing; do not fabricate evidence')
  const data = JSON.parse(fs.readFileSync(file, 'utf8'))
  if (data.evidence_type !== 'measured' || !Array.isArray(data.points) || !data.points.length) {
    throw new Error(side + ': invalid/empty measured curve')
  }
  return data
}
const data = { baseline: read('baseline'), candidate: read('candidate') }
const baseline = new Map(data.baseline.points.map(p => [p.label, p]))
const candidate = new Map(data.candidate.points.map(p => [p.label, p]))
const labels = [...baseline.keys()].filter(label => candidate.has(label))
if (!labels.includes('loaded-10000') || !labels.includes('soak-cleared-30')) {
  throw new Error('Both sides must measure 10k rows and all 30 reopen cycles')
}
const metrics = ['mounted_business_rows', 'total_nodes', 'chromium_heap_used_bytes', 'mount_ms']
const pick = (side, label, name) => Number(data[side].points.find(p => p.label === label)?.[name] ?? NaN)
const format = (name, value) => Number.isFinite(value)
  ? name.includes('bytes') ? (value / 1024 / 1024).toFixed(2) + ' MiB'
    : name.includes('_ms') ? value.toFixed(1) + ' ms' : value.toFixed(0)
  : 'n/a'
const compare = (name, label) => {
  const before = pick('baseline', label, name)
  const after = pick('candidate', label, name)
  return {
    label, metric: name, baseline: Number.isFinite(before) ? before : null,
    candidate: Number.isFinite(after) ? after : null,
    change_pct: Number.isFinite(before) && Number.isFinite(after) && before !== 0
      ? Number(((after / before - 1) * 100).toFixed(2)) : null,
  }
}
const rows = labels.filter(l => ['loaded-1000', 'loaded-10000', 'cleared-10000', 'soak-cleared-30'].includes(l))
  .flatMap(label => metrics.map(metric => compare(metric, label)))
const output = {
  scope: 'synthetic real Vue DataTable in Chromium on the same GitHub Actions runner; not an Electron/Flutter/production service endurance test',
  baseline_sha: data.baseline.source_sha, candidate_sha: data.candidate.source_sha,
  labels, rows, raw: { baseline: data.baseline.points, candidate: data.candidate.points },
}
fs.writeFileSync(path.join(root, 'long-list-comparison.json'), JSON.stringify(output, null, 2))
const lines = [
  '# XCMAX 长列表基线/候选内存实测对比',
  '',
  '来源：Playwright Chromium + Chrome DevTools Protocol，固定合成数据与同一 CI Runner。每个堆采样前主动执行 GC。仅代表合成 Vue 组件，**不代表 Electron/Flutter 真机或 8h/72h 验收**。',
  '',
  'Baseline: `' + data.baseline.source_sha + '`',
  'Candidate: `' + data.candidate.source_sha + '`',
  '',
  '| 测量阶段 | 指标 | 基线 | 候选 | 变化 |',
  '|---|---|---:|---:|---:|',
  ...rows.map(r => '| ' + r.label + ' | ' + r.metric + ' | ' + format(r.metric, r.baseline) + ' | ' +
    format(r.metric, r.candidate) + ' | ' + (r.change_pct === null ? 'n/a' : r.change_pct + '%') + ' |'),
  '',
  '原始数据：`long-list-comparison.json`。如样本外使用量增长，不能仅凭本测试宣称不存在内存泄漏。',
]
fs.writeFileSync(path.join(root, 'long-list-comparison.md'), lines.join('\n') + '\n')
const values = labels.flatMap(label => ['baseline', 'candidate'].map(side =>
  pick(side, label, 'chromium_heap_used_bytes') / 1024 / 1024)).filter(Number.isFinite)
const max = Math.max(1, ...values) * 1.15
const width = 1080, height = 480, left = 72, top = 45, right = 40, bottom = 85
const x = index => left + index * (width - left - right) / Math.max(1, labels.length - 1)
const y = value => height - bottom - value / max * (height - top - bottom)
const series = [['baseline', '#64748b'], ['candidate', '#2563eb']]
const polylines = series.map(([side, color]) =>
  '<polyline fill="none" stroke="' + color + '" stroke-width="3" points="' +
  labels.map((label, i) => {
    const mb = pick(side, label, 'chromium_heap_used_bytes') / 1024 / 1024
    return Number.isFinite(mb) ? x(i).toFixed(1) + ',' + y(mb).toFixed(1) : ''
  }).filter(Boolean).join(' ') + '"/>').join('\n')
const grid = Array.from({ length: 5 }, (_, i) => {
  const value = max * i / 4
  return '<line x1="' + left + '" x2="' + (width - right) + '" y1="' + y(value) + '" y2="' + y(value) +
    '" stroke="#e2e8f0"/><text x="' + (left - 8) + '" y="' + (y(value) + 4) +
    '" text-anchor="end" font-size="12">' + value.toFixed(1) + '</text>'
}).join('')
const marks = labels.map((label, i) => i % Math.max(1, Math.ceil(labels.length / 9)) === 0
  ? '<text x="' + x(i) + '" y="' + (height - bottom + 18) + '" transform="rotate(30 ' + x(i) + ' ' +
     (height - bottom + 18) + ')" font-size="10">' + label + '</text>' : '').join('')
const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '">' +
  '<rect width="100%" height="100%" fill="#fff"/><text x="72" y="25" font-size="20" font-weight="bold">XCMAX Chromium GC 后堆内存曲线 (MiB)</text>' +
  grid + polylines + marks + '<text x="790" y="34" font-size="13" fill="#64748b">基线</text>' +
  '<text x="870" y="34" font-size="13" fill="#2563eb">候选</text>' +
  '<text x="72" y="460" font-size="12" fill="#64748b">30 轮短程循环，仅供同机合成回归；不代表 8h 设备稳定性</text></svg>'
fs.writeFileSync(path.join(root, 'long-list-memory-curve.svg'), svg)
process.stdout.write('Measured long-list comparison saved: ' + rows.length + ' metric rows / ' + labels.length + ' aligned samples\n')
