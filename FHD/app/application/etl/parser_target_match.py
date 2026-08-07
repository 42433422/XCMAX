"""Target-aware header hints and required-field coverage checks."""

from __future__ import annotations

from app.application.etl.errors import EtlError
from app.application.etl.parser_structure import header_match_score
from app.application.etl.parser_types import ParsedDataset


def target_header_hints(target_type: str) -> list[str]:
    try:
        from app.application.etl.targets import get_adapter

        adapter = get_adapter(target_type)
    except EtlError:
        return []
    return [
        value
        for field in adapter.fields
        for value in (field.key, field.label, *field.aliases)
        if value
    ]


def covers_required_target_fields(dataset: ParsedDataset, target_type: str) -> bool:
    from app.application.etl.targets import get_adapter

    required_fields = [field for field in get_adapter(target_type).fields if field.required]
    if not required_fields:
        return True
    pairs = sorted(
        (
            (
                header_match_score(header, (field.key, field.label, *field.aliases)),
                field_index,
                header_index,
            )
            for field_index, field in enumerate(required_fields)
            for header_index, header in enumerate(dataset.headers)
        ),
        reverse=True,
    )
    matched_fields: set[int] = set()
    used_headers: set[int] = set()
    for score, field_index, header_index in pairs:
        if score < 0.75:
            break
        if field_index in matched_fields or header_index in used_headers:
            continue
        matched_fields.add(field_index)
        used_headers.add(header_index)
    return len(matched_fields) == len(required_fields)
