import path from 'node:path'
import fs from 'node:fs'
import type { Session } from 'electron'
import { safeDownloadFilename } from './desktop-navigation'

const configuredSessions = new WeakSet<Session>()
const reservedPaths = new Set<string>()
// Conservative aliases protect pending downloads on case-insensitive Mac volumes.
const reservationKey = (file: string) => file.normalize('NFC').toLowerCase()

export function configureDesktopDownloads(session: Session, directory: () => string, log: (message: string) => void): void {
  if (configuredSessions.has(session)) return
  configuredSessions.add(session)
  session.on('will-download', (_event, item) => {
    let key: string | undefined
    try {
      const folder = directory(), filename = safeDownloadFilename(item.getFilename())
      const extension = path.extname(filename), stem = path.basename(filename, extension)
      let target = path.join(folder, filename), suffix = 0
      while (reservedPaths.has(reservationKey(target)) || fs.lstatSync(target, { throwIfNoEntry: false })) {
        target = path.join(folder, `${stem} (${++suffix})${extension}`)
      }
      key = reservationKey(target)
      reservedPaths.add(key)
      const reservedKey = key
      item.setSavePath(target)
      item.once('done', (_doneEvent, state) => {
        reservedPaths.delete(reservedKey)
        log(`[download] ${state} -> ${target}\n`)
      })
    } catch (error) {
      if (key) reservedPaths.delete(key)
      item.cancel()
      log(`[download] interrupted: ${error instanceof Error ? error.message : 'target unavailable'}\n`)
    }
  })
}
