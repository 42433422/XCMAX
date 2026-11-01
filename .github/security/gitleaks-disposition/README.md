# Gitleaks disposition registry (release-gate)

Committed, secret-free attestations for historical gitleaks findings that have
independent offline evidence (live reject / tip-absent / FP package proof /
credential incident packs resolved via `#2889`).

`normalize_security_report.py` applies this registry after SARIF normalize when
`--scanner gitleaks`. Closing a finding requires:

- fingerprint match `rule|path|commitSha|line`
- `closed: true` disposition class
- author ≠ reviewer
- `review_due` in the future
- listed `evidence_files` present with matching `attestation_sha256`

This is **not** an allowlist weaken: unmatched SARIF results stay `secret: true`.
