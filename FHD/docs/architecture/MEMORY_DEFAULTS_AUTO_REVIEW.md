# Memory defaults and source-grounded automatic review

- WorkingMemory defaults to short- and long-term recall; explicit disable still works.
- Unset/auto embedding prefers already provisioned FastEmbed weights and falls
  back to a stable hash vector space when local weights/dependencies are unavailable.
  Explicit modes still override auto. Provision the existing optional
  intent-semantic dependency and approved weights offline; no default model download.
  Restart after provisioning to select the new fingerprint and let existing
  revision-aware projections rebuild. Do not mix vectors from different spaces.
- Mem0 remains auto-selected; capture/consolidation default on.
- Automatic review is on by default (`XCAGI_MEMORY_AUTO_REVIEW=0` opts out).
  Only authenticated, source-corroborated chat assertions are auto-promoted.
  Explicit private remember requests can pass bounded offline review.
  Model-extracted tenant facts need existing dataset write authority and
  non-personal subject. Global preference sharing, uncertain, sensitive,
  conflicting, unverified or generic agent proposals remain pending.
- Original tenant/Mod and private scopes, revision history, revocation,
  candidate limits, blocked source policy, telemetry off and projection
  validation remain in force. Never bulk-promote old candidates.
- Review policy, decision and reason are recorded on the memory and evidence.
  Enterprise sharing is a default-available capability, not default disclosure.
- Acceptance still requires native FastEmbed cache/model readiness and
  Windows/macOS/server packaging, real authorized shared employee retrieval,
  independent CI and restart/index rebuild evidence.
