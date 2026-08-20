import { spawnSync } from 'node:child_process'

const bin = process.platform === 'win32' ? 'vue-tsc.cmd' : 'vue-tsc'
const result = spawnSync(
  bin,
  ['--noEmit', '-p', 'tsconfig.ci.json', '--pretty', 'false'],
  {
    stdio: 'inherit',
    shell: process.platform === 'win32',
  },
)

if (result.error) {
  throw result.error
}
process.exit(result.status ?? 1)
