"""附件工件：上传文件解析为只读、可按需取数的 artifact。"""

from app.application.attachment_artifacts.models import ArtifactRecord, SheetInfo
from app.application.attachment_artifacts.attachment_parser import (
    AttachmentParseError,
    TemporaryDocument,
    UnsupportedDocument,
    parse_file,
)
from app.application.attachment_artifacts.store import ArtifactStore

__all__ = [
    "ArtifactRecord",
    "ArtifactStore",
    "AttachmentParseError",
    "SheetInfo",
    "TemporaryDocument",
    "UnsupportedDocument",
    "parse_file",
]
