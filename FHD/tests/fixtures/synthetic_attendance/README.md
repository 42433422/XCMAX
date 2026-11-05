# Synthetic attendance regression fixtures

Every employee, identifier, department and punch is invented. No customer workbook is imported,
redacted or used as a value source. SYNTHETIC-001 through SYNTHETIC-080 span all 31 days of March
2026 (2,480 daily rows, 14,880 punches). The template retains the six-row block/calendar/formula
interface: 151 slots, 80 populated synthetic keys, and 16 summary formula columns.

The three Excel employee test modules use these files unconditionally with the in-repository
attendance-industry reference implementation. They compare 7,440 populated record slots;
passing these synthetic tests is not customer acceptance or permission to publish customer data.

The runtime example template is a byte-identical copy for the existing fallback path. It is
sample data, never a customer roster. The Git-index guard blocks known original blobs even if
renamed; it is not a general personal-data detector or a Git-history erasure tool.
