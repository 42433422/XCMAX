# Desktop OTA closed-loop 2026-07-24

## Local (ephemeral Ed25519)

- [x] Serve signed `latest-mac.yml` + ZIP on `127.0.0.1:18765`
- [x] Launch old enterprise app (`656db7b7`) with `XCAGI_UPDATE_URL` + ephemeral pubkey
- [x] `checkForUpdates` → `isUpdateAvailable: true` / remote `7e6ce2689`
- [x] Download extracted into ShipIt cache with matching `buildSha`
- [ ] `quitAndInstall` (skipped to avoid replacing user `/Applications/XCAGI.app` mid-session)

## Production CDN

- [x] New ZIP staged under `releases/stable/xcagi-v1.0.0.0/enterprise/`
- [x] Stable feed restored to last known-good signed `656db7b7` after unsigned upload incident
- [x] CI-signed `latest-mac.yml` for `7e6ce2689` published to stable
- [x] Old app against production feed → `isUpdateAvailable` + `buildSha 7e6ce2689`
