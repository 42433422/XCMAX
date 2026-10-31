"""Shared parsed-dataset value objects for ETL input parsers."""

from __future__ import annotations

import base64
import json
import struct
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from tempfile import SpooledTemporaryFile
from threading import RLock
from typing import Any, overload


@dataclass(slots=True)
class ParsedRow:
    sheet: str
    row_number: int
    values: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)


def _pack(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        # Escape only dictionaries that could impersonate a type tag (or whose
        # keys JSON would coerce). Ordinary CSV/provenance maps stay compact.
        if "$etl" in value or any(not isinstance(key, str) for key in value):
            return {
                "$etl": "dict",
                "value": [[_pack(key), _pack(item)] for key, item in value.items()],
            }
        return {key: _pack(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_pack(item) for item in value]
    if isinstance(value, tuple):
        return {"$etl": "tuple", "value": [_pack(item) for item in value]}
    if isinstance(value, (datetime, date, time)):
        return {"$etl": type(value).__name__, "value": value.isoformat()}
    if isinstance(value, timedelta):
        return {"$etl": "timedelta", "value": [value.days, value.seconds, value.microseconds]}
    if isinstance(value, Decimal):
        return {"$etl": "Decimal", "value": str(value)}
    if isinstance(value, bytes):
        return {"$etl": "bytes", "value": base64.b64encode(value).decode("ascii")}
    return value


def _unpack(value: Any) -> Any:
    if isinstance(value, list):
        return [_unpack(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "$etl" not in value:
        return {key: _unpack(item) for key, item in value.items()}
    kind, data = value["$etl"], value["value"]
    if kind == "dict":
        return {_unpack(key): _unpack(item) for key, item in data}
    if kind == "tuple":
        return tuple(_unpack(item) for item in data)
    if kind == "datetime":
        return datetime.fromisoformat(data)
    if kind == "date":
        return date.fromisoformat(data)
    if kind == "time":
        return time.fromisoformat(data)
    if kind == "timedelta":
        return timedelta(days=data[0], seconds=data[1], microseconds=data[2])
    if kind == "Decimal":
        return Decimal(data)
    if kind == "bytes":
        return base64.b64decode(data)
    raise ValueError("Unknown parsed row value type")


class ParsedRows(Sequence[ParsedRow]):
    """Repeatable rows with bounded buffers and a disk-backed offset index.

    TemporaryFile uses owner-only permissions and is removed on close/process
    exit. No upload path, pickle or executable deserializer is involved. Reads
    return value objects; callers that edit a row must assign it back by index.
    """

    def __init__(self, rows: Iterable[ParsedRow] = ()) -> None:
        self._data = SpooledTemporaryFile(max_size=256 * 1024, mode="w+b")
        self._offsets = SpooledTemporaryFile(max_size=64 * 1024, mode="w+b")
        self._size = 0
        self._data_end = self._data_position = self._offset_position = 0
        self._lock = RLock()
        complete = False
        try:
            for row in rows:
                self.append(row)
            complete = True
        finally:
            if not complete:
                self.close()

    def __len__(self) -> int:
        return self._size

    @overload
    def __getitem__(self, index: int) -> ParsedRow: ...

    @overload
    def __getitem__(self, index: slice) -> list[ParsedRow]: ...

    def __getitem__(self, index: int | slice) -> ParsedRow | list[ParsedRow]:
        if isinstance(index, slice):
            return [self[number] for number in range(*index.indices(self._size))]
        index = self._checked_index(index)
        with self._lock:
            if self._offset_position != index * 8:
                self._offsets.seek(index * 8)
            offset = struct.unpack("<Q", self._offsets.read(8))[0]
            self._offset_position = index * 8 + 8
            if self._data_position != offset:
                self._data.seek(offset)
            size = struct.unpack("<Q", self._data.read(8))[0]
            payload = self._data.read(size)
            self._data_position = offset + 8 + size
            return ParsedRow(*_unpack(json.loads(payload)))

    def __iter__(self) -> Iterator[ParsedRow]:
        for index in range(self._size):
            yield self[index]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Sequence):
            return NotImplemented
        return len(self) == len(other) and all(
            left == right for left, right in zip(self, other, strict=True)
        )

    def _checked_index(self, index: int) -> int:
        if index < 0:
            index += self._size
        if not 0 <= index < self._size:
            raise IndexError(index)
        return index

    def __setitem__(self, index: int, row: ParsedRow) -> None:
        self._write(self._checked_index(index), row)

    def append(self, row: ParsedRow) -> None:
        with self._lock:
            self._write(self._size, row)
            self._size += 1

    def _write(self, index: int, row: ParsedRow) -> None:
        payload = json.dumps(
            _pack([row.sheet, row.row_number, row.values, row.provenance]),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        with self._lock:
            # Keep block buffering during sequential writes/reads. Seeking for
            # every append would flush both files once per row.
            offset = self._data_end
            if self._data_position != offset:
                self._data.seek(offset)
            self._data.write(struct.pack("<Q", len(payload)))
            self._data.write(payload)
            self._data_end = self._data_position = offset + 8 + len(payload)
            if self._offset_position != index * 8:
                self._offsets.seek(index * 8)
            self._offsets.write(struct.pack("<Q", offset))
            self._offset_position = index * 8 + 8

    @property
    def closed(self) -> bool:
        return self._data.closed

    def close(self) -> None:
        try:
            self._data.close()
        finally:
            self._offsets.close()

    def __del__(self) -> None:
        # Preserve the old value-object lifetime for callers that only inspect
        # parse_file results. Workers also close explicitly at their boundary.
        for name in ("_data", "_offsets"):
            stream = getattr(self, name, None)
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass  # Explicit worker close reports I/O errors; GC is best effort.


@dataclass(slots=True)
class ParsedDataset:
    headers: list[str]
    rows: list[ParsedRow] | ParsedRows
    source_features: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def close(self) -> None:
        if isinstance(self.rows, ParsedRows):
            self.rows.close()
