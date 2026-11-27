"""Read-only formula evidence for independent workbook QC; not a calculator."""

from collections import Counter
from hashlib import sha256
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.utils.cell import range_boundaries
from openpyxl.xml.constants import MAX_COLUMN, MAX_ROW

from app.application.reviewed_excel_formula_cells import formula_facts

_DYNAMIC = {"INDIRECT", "OFFSET", "INDEX", "CHOOSE", "LAMBDA", "LET"}
_MAX_BYTES = 40 * 1024 * 1024
_MAX_EXPANDED_BYTES = 128 * 1024 * 1024


def formula_dependency_facts(formula: str, sheet: str) -> dict:
    """Keep lexical reference tokens, not an assumed complete dependency graph."""
    refs, unresolved = [], []
    if not formula or not formula.startswith("=") or not formula[1:].strip():
        return {"references": refs, "unresolved": ["missing_formula_text"]}
    try:
        tokens = Tokenizer(formula).items
    except (TokenizerError, IndexError):
        # openpyxl 3.1.5 raises IndexError on an unmatched closing delimiter.
        return {"references": refs, "unresolved": ["unsupported_formula_syntax"]}
    for token in tokens:
        if token.type == "FUNC" and token.subtype == "OPEN":
            name = token.value[:-1].upper().rsplit(".", 1)[-1]
            if name in _DYNAMIC:
                unresolved.append("dynamic_reference")
        if token.type == "OPERAND" and token.subtype == "ERROR":
            unresolved.append("error_operand")
        if token.type != "OPERAND" or token.subtype != "RANGE":
            continue
        prefix, separator, address = token.value.rpartition("!")
        target = prefix.removeprefix("'").removesuffix("'").replace("''", "'")
        if separator and "[" in prefix:
            kind = "external"
        elif separator and ":" in prefix:
            kind = "three_dimensional"
        elif "[" in address:
            kind = "structured"
        else:
            try:
                bounds = range_boundaries(address)
                c1, r1, c2, r2 = bounds
                is_range = (
                    (":" in address or all(part is not None for part in bounds))
                    and all(1 <= c <= MAX_COLUMN for c in (c1, c2) if c is not None)
                    and all(1 <= row <= MAX_ROW for row in (r1, r2) if row is not None)
                    and (c1 is None or c2 is None or c1 <= c2)
                    and (r1 is None or r2 is None or r1 <= r2)
                )
            except ValueError:
                is_range = False
            kind = ("cross_sheet" if separator else "local") if is_range else "named_or_unknown"
        if kind not in {"local", "cross_sheet"}:
            unresolved.append(kind)
        refs.append({"token": token.value, "sheet": target if separator else sheet, "kind": kind})
    return {"references": refs, "unresolved": sorted(set(unresolved))}


def summarize_formula_evidence(body: bytes, *, qc_formula_count: int | None = None) -> dict:
    """Bind observed XML caches to exact bytes; never infer freshness or calculation."""
    report = {
        "artifact_sha256": sha256(body).hexdigest(),
        "qc_formula_count": qc_formula_count,
        "coverage": "not_proven",
        "recalculation_status": "not_run",
        "formula_recalculation_verified": False,
    }
    if len(body) > _MAX_BYTES:
        return {**report, "status": "blocked_resource_budget"}
    try:
        with ZipFile(BytesIO(body)) as archive:
            if sum(item.file_size for item in archive.infolist()) > _MAX_EXPANDED_BYTES:
                return {**report, "status": "blocked_resource_budget"}
    except BadZipFile:
        return {**report, "status": "invalid_archive"}
    facts = formula_facts(body)
    caches, references, unresolved = Counter(), Counter(), Counter()
    for (sheet, _), fact in facts.items():
        caches["missing_or_empty" if fact["cache_missing"] else "present_unverified"] += 1
        dependency = formula_dependency_facts(fact["formula"], sheet)
        references.update(item["kind"] for item in dependency["references"])
        unresolved.update(dependency["unresolved"])
    return {
        **report,
        "status": "observed" if facts else "no_formula_facts",
        "observed_formula_count": len(facts),
        "cache_states": dict(caches),
        "reference_token_counts": dict(references),
        "unresolved_dependency_counts": dict(unresolved),
        "dependency_scope": "lexical_tokens_only",
    }
