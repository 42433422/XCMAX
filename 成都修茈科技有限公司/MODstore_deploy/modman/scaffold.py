from __future__ import annotations

import os
import shutil
from pathlib import Path


def template_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / "skeleton"


def create_mod(mod_id: str, mod_name: str, library: Path) -> Path:
    mod_id = mod_id.strip().lower().replace(" ", "-")
    if not mod_id:
        raise ValueError("mod_id 不能为空")
    td = template_dir()
    if not td.is_dir():
        raise FileNotFoundError(f"缺少模板目录: {td}")
    library_text = os.path.realpath(os.path.abspath(library))
    dest_text = os.path.realpath(os.path.abspath(os.path.join(library_text, mod_id)))
    library_prefix = library_text.rstrip(os.sep) + os.sep
    if dest_text != library_text and not dest_text.startswith(library_prefix):
        raise ValueError("mod_id 路径越界")
    library = Path(library_text)
    dest = Path(dest_text)
    if dest.exists():
        raise FileExistsError(f"已存在: {dest}")
    library.mkdir(parents=True, exist_ok=True)
    shutil.copytree(td, dest)
    for path in dest.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".js", ".vue", ".py"}:
            text = path.read_text(encoding="utf-8")
            text = text.replace("__MOD_ID__", mod_id)
            text = text.replace("__MOD_NAME__", mod_name)
            path.write_text(text, encoding="utf-8")
    return dest
