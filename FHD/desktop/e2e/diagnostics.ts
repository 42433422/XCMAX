import type { TestInfo } from '@playwright/test'
import type { ChildProcess } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

export function preserveElectronDiagnostics(child: ChildProcess | undefined, userDataDir: string, testInfo: TestInfo): void {
  const capture = (name: string, write: () => void): void => {
    try { write() } catch (error) { console.warn(`[electron diagnostics] Failed to preserve ${name}:`, error) }
  }
  for (const relative of ['logs/electron-backend.log', 'session-lifecycle.json', 'crash-dumps']) {
    capture(relative, () => {
      const source = path.join(userDataDir, relative)
      if (fs.existsSync(source)) fs.cpSync(source, testInfo.outputPath(path.basename(relative)), { recursive: true })
    })
  }
  if (child) capture('electron-exit.json', () => {
    const exit = { exitCode: child.exitCode, signalCode: child.signalCode }
    console.info('[electron diagnostics] exit:', exit)
    fs.writeFileSync(testInfo.outputPath('electron-exit.json'), JSON.stringify(exit))
  })
}
