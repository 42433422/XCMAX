# Persy L5/L6 governance increment

Depends on the L4 relation/revision PR (#3528). Reuses MemoryV2 as authority.

- Revoked or superseded scoped memory fingerprints are not automatically re-proposed, including enterprise shared memory and global preferences.
- Lexical-only recall rechecks current authoritative revision, just as graph recall does.
- Cross-actor lifecycle regression covers pending review, confirmation, read-only role, private isolation, tenant/Mod isolation, correction, deletion and replay suppression. This is an application-service test, not proof of actual employee runtime integration.

Remaining L6 gates: prove authorized multi-employee task handoff and shared retrieval in real Agent runs; explicitly review promotion of independently verified outcome evidence to enterprise scope without copying private data; validate concurrency, restart and projection recovery; real-model extraction/identity evaluation; independent production tenant/Mod ACL and real business acceptance. Do not claim production L6 until these pass.
