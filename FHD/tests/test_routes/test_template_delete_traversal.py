"""回归测试：模板删除路径遍历漏洞（VULN-3）。

针对 ``app.fastapi_routes.document_templates_compat.run_archive_template_delete``
的 ``fs:`` 分支：合法 id 永远是裸文件名（来自 os.listdir）。任何含目录分隔符、
``..`` 或绝对路径的输入都属于路径遍历攻击。

修复前：``os.path.join(root, "/etc/hosts")`` 会丢弃 root 直接得到 ``/etc/hosts``，
``fs:/etc/hosts`` / ``fs:../../secret.txt`` 可删除仓库外任意文件。
修复后：这些 payload 被拒（4xx），os.remove 不会被以越界路径调用，合法裸文件名
删除仍正常。
"""

from __future__ import annotations

import os

from app.fastapi_routes.document_templates_compat import run_archive_template_delete


def test_absolute_path_traversal_is_rejected(tmp_path):
    """fs:/etc/hosts 被拒，且 tmp 外的真实文件不会被删除。"""
    # 在 tmp 外造一个"受害"文件，作为遍历目标的替身（不动真正的 /etc/hosts）。
    victim = tmp_path.parent / "victim_abs_traversal.txt"
    victim.write_text("do-not-delete", encoding="utf-8")
    try:
        payload = {"id": f"fs:{victim}"}
        data, code = run_archive_template_delete(payload, base_dir=str(tmp_path))
        assert code >= 400, f"期望 4xx，实际 {code}: {data}"
        assert data.get("success") is False
        assert victim.exists(), "遍历 payload 不应删除 tmp 外文件"
    finally:
        if victim.exists():
            victim.unlink()


def test_relative_path_traversal_is_rejected(tmp_path):
    """fs:../../secret.txt 被拒，且对应文件不会被删除。"""
    secret = tmp_path.parent / "secret_rel_traversal.txt"
    secret.write_text("top-secret", encoding="utf-8")
    try:
        payload = {"id": "fs:../../secret_rel_traversal.txt"}
        data, code = run_archive_template_delete(payload, base_dir=str(tmp_path))
        assert code >= 400, f"期望 4xx，实际 {code}: {data}"
        assert data.get("success") is False
        assert secret.exists(), "遍历 payload 不应删除目标文件"
    finally:
        if secret.exists():
            secret.unlink()


def test_legitimate_bare_filename_delete_succeeds(tmp_path):
    """合法裸文件名 fs:a.docx 正常删除，返回结构不变。"""
    target = tmp_path / "a.docx"
    target.write_text("template body", encoding="utf-8")

    payload = {"id": "fs:a.docx"}
    data, code = run_archive_template_delete(payload, base_dir=str(tmp_path))

    assert code == 200, f"期望 200，实际 {code}: {data}"
    assert data.get("success") is True
    assert data.get("deleted", {}).get("id") == "fs:a.docx"
    assert "path" in data.get("deleted", {})
    assert not target.exists(), "合法删除后文件应被移除"


def test_legitimate_delete_in_templates_subdir(tmp_path):
    """受信任的 templates/ 子目录下的裸文件名删除成功。"""
    sub = tmp_path / "templates"
    sub.mkdir()
    target = sub / "b.xlsx"
    target.write_text("xlsx body", encoding="utf-8")

    data, code = run_archive_template_delete({"id": "fs:b.xlsx"}, base_dir=str(tmp_path))

    assert code == 200, f"{code}: {data}"
    assert data.get("success") is True
    assert not target.exists()


def test_os_remove_not_called_on_traversal(tmp_path, monkeypatch):
    """遍历 payload 时 os.remove 绝不被以越界路径调用。"""
    victim = tmp_path.parent / "victim_no_remove.txt"
    victim.write_text("keep-me", encoding="utf-8")

    removed_paths: list[str] = []
    real_remove = os.remove

    def _tracking_remove(path, *args, **kwargs):
        removed_paths.append(str(path))
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(os, "remove", _tracking_remove)

    try:
        for bad_id in (
            f"fs:{victim}",
            "fs:../../victim_no_remove.txt",
            "fs:../../../../etc/hosts",
            "fs:/etc/hosts",
            "fs:foo/bar.docx",
            "fs:..",
        ):
            data, code = run_archive_template_delete({"id": bad_id}, base_dir=str(tmp_path))
            assert code >= 400, f"{bad_id} 应被拒，实际 {code}: {data}"

        assert removed_paths == [], f"遍历 payload 不应触发 os.remove，但调用了: {removed_paths}"
        assert victim.exists()
    finally:
        if victim.exists():
            victim.unlink()


def test_symlink_escape_is_rejected(tmp_path):
    """受信任目录中的符号链接指向外部文件时，删除被拒，外部文件保留。"""
    outside = tmp_path.parent / "outside_symlink_target.txt"
    outside.write_text("external", encoding="utf-8")
    link = tmp_path / "evil.docx"
    try:
        os.symlink(str(outside), str(link))
    except (OSError, NotImplementedError):
        # 平台不支持符号链接则跳过本断言（不视为失败）。
        outside.unlink()
        return

    try:
        data, code = run_archive_template_delete({"id": "fs:evil.docx"}, base_dir=str(tmp_path))
        assert code >= 400, f"符号链接逃逸应被拒，实际 {code}: {data}"
        assert outside.exists(), "符号链接目标（外部文件）不应被删除"
    finally:
        if link.exists() or os.path.islink(str(link)):
            os.unlink(str(link))
        if outside.exists():
            outside.unlink()
