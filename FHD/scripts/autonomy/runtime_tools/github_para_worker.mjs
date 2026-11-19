/** A bounded GitHub job around the existing Para agent; no model or repair implementation. */
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

export async function runGithubWorker({ env = process.env } = {}) {
  // Environment filtering cannot isolate same-UID processes from publisher credentials.
  // Use the separate executor/publisher jobs in para-github-worker.yml instead.
  // No runtime flag may bypass this legacy entry point's guard.
  const reason = 'blocked_isolated_publisher_required';
  if (env.PARA_GITHUB_EVIDENCE_DIR) {
    mkdirSync(env.PARA_GITHUB_EVIDENCE_DIR, { recursive: true });
    writeFileSync(join(env.PARA_GITHUB_EVIDENCE_DIR, 'execution.json'), JSON.stringify({
      request_id: env.PARA_GITHUB_REQUEST_ID, run_id: env.GITHUB_RUN_ID,
      finished: true, conclusion: 'failure', status: 'blocked', reason,
      executor: 'Para', machine: 'github-hosted', source_sha: env.GITHUB_SHA,
    }, null, 2) + '\n');
  }
  throw new Error(reason);

}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runGithubWorker().then(code => { process.exitCode = code; }).catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
