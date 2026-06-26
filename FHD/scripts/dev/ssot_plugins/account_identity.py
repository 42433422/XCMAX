"""account-identity 域适配器：身份真相源守卫（棘轮）。

真相源声明见 docs/account_system_ssot.md（§零 身份权威总则、§九 解析入口与移动端 JWT 契约）：
**认证与身份归属以云端（修茈市场）为准；本地 users/sessions 行只是会向云端收敛的缓存。**

本守卫只做一件事：冻结当前已知的「造身份」点，禁止白名单外再新增。
扫描 app/ 下两类身份伪造模式：
1. JWT → 用户对象：``SimpleNamespace(id=…, role=… / username=…)`` 凭 payload 凭空造用户。
2. 空密码建号：``User(…, password="")`` —— 空密码用户应禁止登录。

白名单内 = 已登记的受控点（云端为前置权威，或已知技术债）；白名单外新增 = DRIFT。
advisory 域：报告但不硬阻断（统一 gate continue-on-error）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

_FHD_ROOT = Path(__file__).resolve().parents[3]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))
from scripts.dev.ssot_plugins.base import ROOT  # noqa: E402

APP_ROOT = ROOT / "app"

# 受控「造身份」点白名单（相对 FHD/ 路径 → 准入理由）。
# 新增身份伪造点必须先在 docs/account_system_ssot.md §9.3 登记，再加入此处。
ALLOWLIST: dict[str, str] = {
    "app/fastapi_routes/mobile_api.py": (
        "_mobile_user_from_jwt_payload：云端签发的移动 JWT 作为身份载体"
        "（仅 admin/admin_portal 或 mobile-relay- 会话，已登记 §9.2）"
    ),
    # 原 xcmax_admin.py 空密码占位建号已收口（改用不可用哨兵哈希，见 §9.3），
    # 故从白名单移除：任何位置再写空密码 User(...) 即 DRIFT。
}


def _last_name(func: ast.expr) -> str:
    """取调用名的最后一段：Name -> id；Attribute -> attr。"""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_user_simplenamespace(node: ast.Call) -> bool:
    """SimpleNamespace(...) 且含 id= 与 (role= 或 username=) —— 凭空造用户。"""
    if _last_name(node.func) != "SimpleNamespace":
        return False
    kws = {kw.arg for kw in node.keywords if kw.arg}
    return "id" in kws and bool(kws & {"role", "username"})


def _is_empty_password_user(node: ast.Call) -> bool:
    """User(..., password="") —— 空密码建号。"""
    if _last_name(node.func) != "User":
        return False
    for kw in node.keywords:
        if kw.arg == "password" and isinstance(kw.value, ast.Constant):
            if kw.value.value == "":
                return True
    return False


def _scan() -> list[tuple[str, int, str]]:
    """返回 [(相对路径, 行号, 模式)]。"""
    hits: list[tuple[str, int, str]] = []
    if not APP_ROOT.is_dir():
        return hits
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _is_user_simplenamespace(node):
                hits.append((rel, node.lineno, "JWT→SimpleNamespace 用户"))
            elif _is_empty_password_user(node):
                hits.append((rel, node.lineno, "空密码 User()"))
    return hits


def check_drift() -> int:
    """只读检查：app/ 内身份伪造点不超出白名单。"""
    if not APP_ROOT.is_dir():
        print(f"account-identity: app 目录不存在 {APP_ROOT}", flush=True)
        return 2

    hits = _scan()
    violations = [(rel, ln, kind) for rel, ln, kind in hits if rel not in ALLOWLIST]
    sanctioned = [(rel, ln, kind) for rel, ln, kind in hits if rel in ALLOWLIST]

    if violations:
        print(f"account-identity: {len(violations)} 个白名单外的造身份点（DRIFT）", flush=True)
        for rel, ln, kind in violations:
            print(
                f"  - {rel}:{ln} [{kind}] —— 身份须由唯一入口解析；如确需，先登记 §9.3 再加白名单",
                flush=True,
            )
        return 1

    print(
        f"account-identity: OK（{len(sanctioned)} 个受控造身份点全部在白名单内，无新增）",
        flush=True,
    )
    for rel, ln, kind in sanctioned:
        print(f"  · {rel}:{ln} [{kind}] —— {ALLOWLIST[rel]}", flush=True)
    return 0


def run(action: str, domain: dict[str, Any], *, dry_run: bool = True) -> int:
    if action == "check":
        return check_drift()
    if action == "sync":
        print("account-identity: lint 模式无 sync", flush=True)
        return 0
    return 2


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    raise SystemExit(run(action, {}, dry_run=True))
