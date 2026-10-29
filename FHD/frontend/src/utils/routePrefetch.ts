/** Each worker retains its slot until the import settles, including rejected imports. */
export async function prefetchRouteChunks(
  loaders: Array<() => Promise<unknown>>,
  idle: (task: () => void) => void,
  concurrency = 4,
): Promise<void> {
  const jobs = [...new Set(loaders)]
  let index = 0
  const worker = async () => {
    while (index < jobs.length) {
      const job = jobs[index++]
      await new Promise<void>((resolve) => idle(resolve))
      try { await job() } catch { /* Navigation can retry an unavailable chunk. */ }
    }
  }
  await Promise.all(Array.from({ length: Math.min(jobs.length, Math.max(1, Math.floor(concurrency) || 1)) }, worker))
}
