#!/usr/bin/env python3
"""Reject customer runtime artifacts in the Git index, including forced adds.

This is a current-tree path guard, not a claim to detect every personal value or
erase Git history. Legitimate synthetic fixtures and business templates remain
allowed outside runtime/upload locations.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

CORP = "成都修茈科技有限公司/"
MODSTORE = CORP + "MODstore_deploy/"
PREFIXES = (
    "outputs/",
    MODSTORE + "var/employee_draft_assets/",
    MODSTORE + "var/employee_uploads/",
    MODSTORE + "modstore_server/data/payment_orders/",
    MODSTORE + "modstore_server/data/chroma/",
    "FHD/delivery/sunbird-seed/424/",
    "FHD/delivery/sunbird-seed/data/",
    "FHD/XCAGI/.backups/",
    "FHD/app/resources/ai_assistant/商标导出/",
    "FHD/resources/ai_assistant/商标导出/",
)
EXACT = {
    "FHD/delivery/sunbird-seed/config/sunbird-roster.json",
    "FHD/XCAGI/.test_db_state.json",
}
BLOCKED_BLOBS = frozenset(
    {
        "bcc11bbe86cc06f0118c7cccc6a79df51b9aed7b",
        "ecb796962919a25cddcb5b5a25dead16683fa1d4",
        "7ceeb82192ebb0c4b034428de6b445fbfbdd50a4",
        "d1493ef3884456992485c579acf06adbbfbb8f8d",
        "a8995d340f6f17e54fb9dbc180dedf485b602f71",
        "a976117af5c47c7bdd6f00b40acc036665027a7e",
        "e43218ecfa360805d9b3e802dba37902e69b94a8",
        "25e705e188f494fe3b7af2d9875580aae9e26929",
        "2792ea764f5e9e9385b5006f4adc039bc4d8ac6a",
        "c335e2011f83f6e9024feee9e71f9b8bc8f5f2c5",
        "569db365a840d7916f66fdaa30ba4f20b5664746",
        "da1839d345f22ceb9024e64af7bcaf931bcd4c9b",
        "cfd5dcb0aaa9e1eb718867712384a23d6d7524ac",
        "bfc8897b71dff4ed972ee84b5292061cec7e6171",
        "d975ca3b41f10bfc4ba36fa1e85f2cd62fbdfecf",
        "f3dd629bbcf4fc3ce321e268dc76f8f913375eb4",
        "16c6c4923c72492d44a472e2b50539d8cbf89984",
    }
)


def _path_pattern(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.DOTALL)


PATTERNS = (
    _path_pattern(
        r"FHD/(?:XCAGI/监控|tools/bartender-monitor)/window_.*\.(?i:png|jpe?g)$"
    ),
    _path_pattern(r"FHD/\.cursor/.*\.docx$"),
    _path_pattern(re.escape(MODSTORE) + r"modstore_server/webhook_events/.*\.json$"),
    _path_pattern(
        re.escape(MODSTORE) + r"modstore_server/data/event_outbox(?:_.*)?\.jsonl$"
    ),
    _path_pattern(re.escape(MODSTORE) + r"modstore_server/payment_orders/.*\.json$"),
    _path_pattern(re.escape(CORP) + r"taiyangniao-pro/backend/_conv_.*\.xlsx$"),
)


def forbidden(path: str) -> bool:
    return (
        path in EXACT
        or path.startswith(PREFIXES)
        or any(p.fullmatch(path) for p in PATTERNS)
    )


def indexed_entries(root: Path) -> list[tuple[str, str]]:
    # NUL delimiters preserve Chinese, whitespace and newlines. Do not inspect
    # working-tree existence: a deleted local file may still be in the index.
    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"], cwd=root, check=True, capture_output=True
    )
    entries = []
    for record in result.stdout.decode("utf-8", errors="surrogateescape").split("\0"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        _mode, sha, _stage = metadata.split()
        entries.append((path, sha))
    return entries


def main(root: Path | None = None) -> int:
    root = root or Path(__file__).resolve().parents[2]
    blocked = sorted(
        {
            path
            for path, sha in indexed_entries(root)
            if forbidden(path) or sha in BLOCKED_BLOBS
        }
    )
    for path in blocked:
        print(f"Forbidden tracked customer/runtime artifact: {path!r}")
    if blocked:
        print(
            "Remove these paths from the proposed tree; keep customer data in private runtime storage."
        )
        return 1
    print("No forbidden customer/runtime paths in the proposed Git index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
