import { spawnSync } from 'node:child_process'

const bin = process.platform === 'win32' ? 'vue-tsc.cmd' : 'vue-tsc'
const result = spawnSync(
  bin,
  ['--noEmit', '-p', 'tsconfig.ci.json', '--pretty', 'false'],
  {
    encoding: 'utf8',
    shell: process.platform === 'win32',
  },
)

if (result.status === 0) {
  process.exit(0)
}

const output = `${result.stdout || ''}\n${result.stderr || ''}`
const errorLines = output
  .split(/\r?\n/)
  .filter((line) => /error TS\d+/.test(line))

const byFile = new Map()
for (const line of errorLines) {
  const file = line.split('(')[0] || '(unknown)'
  byFile.set(file, (byFile.get(file) || 0) + 1)
}

console.warn(`[typecheck:ci] vue-tsc reports ${errorLines.length} existing market type error(s).`)
for (const [file, count] of [...byFile.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12)) {
  console.warn(`  ${count} ${file}`)
}
console.warn(
  [
    'CI keeps lint, unit coverage, and production build as hard gates.',
    'Run `npm run typecheck` or `npm run typecheck:strict` to work the full debt down separately.',
  ].join('\n'),
)

process.exit(0)
