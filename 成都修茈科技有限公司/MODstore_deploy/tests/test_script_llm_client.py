from __future__ import annotations

from modstore_server.script_agent.llm_client import extract_code_block


def test_extract_code_block_prefers_python_fence():
    raw = (
        "这是说明，不是代码。\n"
        "```python\n"
        "from pathlib import Path\n"
        "Path('outputs').mkdir(exist_ok=True)\n"
        "print('ok')\n"
        "```\n"
        "以上。"
    )
    code = extract_code_block(raw)
    assert code.startswith("from pathlib import Path")
    assert "print('ok')" in code


def test_extract_code_block_strips_leading_prose_when_no_fence():
    raw = "先给出实现思路：\nfrom pathlib import Path\nprint('ok')\n"
    code = extract_code_block(raw)
    assert code.startswith("from pathlib import Path")
    assert "思路" not in code.splitlines()[0]


def test_extract_code_block_supports_json_code_payload():
    raw = '{"code":"from pathlib import Path\\nprint(\\"ok\\")"}'
    code = extract_code_block(raw)
    assert code.startswith("from pathlib import Path")
    assert 'print("ok")' in code


def test_extract_code_block_docstring_with_inner_markdown_fences():
    """Non-greedy fence regex used to stop at the first ``` inside a docstring."""
    raw = '''说明如下。
```python
from pathlib import Path

OVERVIEW = """
示例 CLI：

```
npm run build
```

收尾。
"""

def main():
    Path("outputs").mkdir(exist_ok=True)
    (Path("outputs") / "summary.md").write_text(OVERVIEW, encoding="utf-8")

if __name__ == "__main__":
    main()
```
'''
    code = extract_code_block(raw)
    ast_ok = False
    try:
        compile(code, "<extracted>", "exec")
        ast_ok = True
    except SyntaxError:
        pass
    assert ast_ok, code[:400]
    assert "npm run build" in code
    assert "OVERVIEW" in code
