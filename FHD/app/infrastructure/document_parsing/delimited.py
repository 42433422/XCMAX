"""Shared lossless CSV/TSV decoding for ELT and Office employees (stdlib csv)."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from typing import Protocol, TextIO


class DelimitedReader(Protocol):
    @property
    def line_num(self) -> int: ...

    def __iter__(self) -> Iterator[list[str]]: ...

    def __next__(self) -> list[str]: ...


def decode_delimited(raw: bytes) -> tuple[str, str]:
    encodings = (
        ("utf-16",) if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "gb18030")
    )
    for encoding in encodings:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV/TSV encoding is unsupported; refusing lossy decoding")


def delimited_reader(raw: bytes, *, suffix: str = ".csv") -> tuple[TextIO, DelimitedReader, dict]:
    text, encoding = decode_delimited(raw)
    try:
        delimiter = (
            "\t"
            if suffix == ".tsv"
            else csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
        )
    except csv.Error:
        delimiter = ","
    handle = StringIO(text, newline="")
    # No splitlines, whitespace trimming or DictReader: all three lose native facts.
    reader = csv.reader(handle, delimiter=delimiter, strict=True)
    return handle, reader, {"encoding": encoding, "delimiter": delimiter}


def open_delimited(path: Path) -> tuple[TextIO, DelimitedReader, dict]:
    # Validate the complete encoding before streaming records; a late invalid byte
    # must not silently switch encodings after already emitting business rows.
    with path.open("rb") as raw:
        prefix = raw.read(2)
    encodings = ("utf-16",) if prefix in {b"\xff\xfe", b"\xfe\xff"} else ("utf-8-sig", "gb18030")
    for encoding in encodings:
        handle = path.open("r", encoding=encoding, newline="")
        try:
            sample = handle.read(8192)
            while handle.read(64 * 1024):
                pass
            handle.seek(0)
            try:
                delimiter = (
                    "\t"
                    if path.suffix.lower() == ".tsv"
                    else csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
                )
            except csv.Error:
                delimiter = ","
            return (
                handle,
                csv.reader(handle, delimiter=delimiter, strict=True),
                {"encoding": encoding, "delimiter": delimiter},
            )
        except UnicodeDecodeError:
            handle.close()
    raise ValueError("CSV/TSV encoding is unsupported; refusing lossy decoding")


def column_keys(
    headers: list[str],
    width: int,
    *,
    empty_prefix: str = "__column_",
    duplicate_separator: str = "__",
) -> list[str]:
    """Lossless compatibility keys; original headers remain separately available."""
    keys: list[str] = []
    occupied = set(headers)
    used: set[str] = set()
    next_suffix: dict[str, int] = {}
    for index in range(width):
        original = headers[index] if index < len(headers) else ""
        key = original or f"{empty_prefix}{index + 1}"
        if not original or key in used:
            stem = key
            counter = next_suffix.get(stem, 2)
            while key in occupied or key in used:
                key = f"{stem}{duplicate_separator}{counter}"
                counter += 1
            next_suffix[stem] = counter
        keys.append(key)
        used.add(key)
    return keys
