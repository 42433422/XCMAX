/** Collect actual Vitest results; native blob merger remains the coverage authority. */
import assert from 'node:assert/strict'
import { readFileSync, writeFileSync } from 'node:fs'
import { coverageEvidence, executionEvidence, relativeFile, uniqueFiles } from './frontend_shard_evidence.mjs'

export default class FrontendShardReporter {
  onInit(ctx) {
    this.ctx = ctx
    this.root = ctx.config.root
    this.output = process.env.FRONTEND_SHARD_REPORT
    assert(this.output, 'FRONTEND_SHARD_REPORT is required')
    this.phase = process.env.FRONTEND_SHARD_PHASE
    assert(['collect', 'merge'].includes(this.phase), 'Explicit frontend shard phase is required')
    if (this.phase === 'merge') {
      // Vitest 5.0 blob data is decoded by Vitest itself before onInit. Fail on
      // an incompatible API instead of silently accepting missing raw coverage.
      const plan = JSON.parse(readFileSync(process.env.FRONTEND_SHARD_MERGE_PLAN, 'utf8'))
      const blobs = ctx.state.blobs
      assert(Array.isArray(blobs?.coverages), 'Native Vitest blob coverage is unavailable')
      const actual = blobs.coverages.map(raw => coverageEvidence(raw, this.root).sha256).sort()
      assert.deepEqual(actual, plan.coverages.map(item => item.sha256).sort(), 'Missing, duplicated or changed blob coverage')
    }
  }

  onCoverage(coverage) {
    this.coverage = coverageEvidence(coverage, this.root)
  }

  async onTestRunStart(specifications) {
    this.collection = uniqueFiles(specifications.map(spec => relativeFile(spec.moduleId, this.root)))
    // Vitest 5 announces the complete collection before its pool partitions it.
    // Ask its configured sequencer for the selection; do not copy its hashing
    // algorithm or trust `list --filesOnly --shard` (which lists all files).
    const selected = this.phase === 'collect'
      ? await new this.ctx.config.sequence.sequencer(this.ctx).shard([...specifications])
      : specifications
    this.selected = uniqueFiles(selected.map(spec => relativeFile(spec.moduleId, this.root)))
  }

  onTestRunEnd(modules, errors) {
    let result
    try {
      result = { success: true, ...executionEvidence(modules, errors, this.root) }
      assert.deepEqual(result.files, this.selected, 'Missing/extra selected file execution')
      if (this.phase === 'collect') {
        assert(this.coverage, 'Vitest did not collect raw V8 coverage')
        result.coverage = this.coverage
        result.collection = this.collection
      }
    } catch (error) {
      result = { success: false, error: String(error.message) }
      console.error(`[frontend-shard-report] ${error.stack || error}`)
      process.exitCode = 1
    }
    writeFileSync(this.output, JSON.stringify(result, null, 2) + '\n')
  }
}
