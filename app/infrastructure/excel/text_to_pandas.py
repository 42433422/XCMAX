"""生成代码校验与受限 pandas 执行辅助。

Phase 3B 从 ``app.legacy.excel_text_to_pandas`` 吸收。
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _validate_generated_code(code: str) -> str | None:
    banned = ("__class__", "__globals__", "__dict__", "import ", "exec(", "eval(")
    c = code or ""
    for b in banned:
        if b in c:
            return f"unsafe token: {b}"
    return None


def _safe_exec_pandas(code: str, df: pd.DataFrame) -> pd.DataFrame:
    err = _validate_generated_code(code)
    if err:
        raise ValueError(err)
    env: dict[str, Any] = {"df": df.copy(), "pd": pd, "result": None}
    exec(code, {"__builtins__": {}}, env)
    result = env.get("result")
    if isinstance(result, pd.DataFrame):
        return result
    if isinstance(result, pd.Series):
        return result.to_frame()
    return df.head(0)


__all__ = ["_validate_generated_code", "_safe_exec_pandas"]
