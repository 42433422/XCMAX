# Wallet and plans browser sign-in

The desktop never places a reusable market access/refresh token in a URL. Its wallet,
plan and recharge links contain only purchase parameters. A click requests a 60-second
code using the authenticated FHD session; rendering or prefetching a link does not issue
credentials. Electron passes the resulting trusted HTTPS URL to the system browser.
Ordinary browsers open a blank popup during the click and navigate it after issuance.

MODstore stores only the SHA-256 code digest, issuing user ID, password fingerprint,
purpose, exact normalized relative target, expiry and consumption time. The only targets
are `/wallet` and `/plans`, with an allowlist of purchase parameters. A conditional
`UPDATE ... RETURNING` consumes the code atomically across workers. Expired, replayed,
wrong-purpose, wrong-target, disabled-account and changed-password requests fail.
The browser receives the code in its fragment, removes it before bootstrap requests,
and redeems it in a POST body. Tokens are returned in a no-store response; an account
switch replaces both the previous access and refresh token.

The legacy `xcagi_mt` query/fragment is stripped without being accepted as authentication.
The user sees a login explanation and can continue to the clean purchase target.
`GET /api/market/session-handoff` keeps its local SPA credential-response fields but
requires a verified matching session and returns only that session's credentials, with
`Cache-Control: no-store`. Anonymous/error/latest-session fallbacks are removed. Normal
local-session entitlement refresh remains in place. Session errors require re-login;
this compatibility boundary is intentional and prevents borrowing another user's identity.

FHD registers these routes through `legacy_compat._register_early_critical_routes`, which
mounts the `market_account` facade with its existing `/api/market` prefix. The model-payment
Mod calls this host route. MODstore mounts `market_auth_api` through
`_include_router_without_method_conflicts` with `/api`; the child handoff router supplies
`/auth/browser-handoff`. Runtime-registration tests exercise both actual mount paths and
the FHD cookie-to-database session chain, including conflicting session headers.

## Release order

1. Apply MODstore Alembic migration `20260905_browser_handoff` after
   `20260904_asset_install_cmd`. Deploy its issue/consume APIs and the FHD broker/legacy
   GET hardening. Verify the table, fixed targets, denied anonymous calls and replay rejection.
2. Deploy Market frontend consumption and startup URL stripping. Verify a newly issued
   code reaches the correct wallet/selected plan; a legacy or expired URL reaches a clean
   login page without writing its token to storage. Deploy these before new desktop clients.
3. Sync `xcagi-model-payment-bridge` from `FHD/mods` with `mods_ssot.py`, build and release
   the signed desktop. On an installed Electron client, test wallet, each plan and recharge
   navigation through the existing trusted external-URL handler. Also verify ordinary browser
   popup failure and re-login recovery. No real payment is required for navigation validation.

If a rollout is incomplete, retain clean links and the normal Market login flow. Never
restore reusable URL-token consumption as a fallback. Do not log raw URLs, request bodies,
code values or upstream authentication error bodies. Desktop denial/open failures deliberately
use fixed messages because Electron shell errors may echo a full credential-bearing URL.
