"""semantic_quality + static_checker integration."""

from __future__ import annotations

from modstore_server.script_agent.semantic_quality import (
    MAX_STRING_LITERAL_CHARS,
    oversized_string_literal_errors_for_source,
)
from modstore_server.script_agent.static_checker import validate_script


def test_oversized_literal_flagged():
    big = "x" * (MAX_STRING_LITERAL_CHARS + 50)
    src = f'a = """{big}"""\n'
    errs = oversized_string_literal_errors_for_source(src)
    assert errs


def test_validate_script_includes_semantic_errors():
    big = "y" * (MAX_STRING_LITERAL_CHARS + 10)
    code = "\n".join(
        [
            "from pathlib import Path",
            f'DUMP = """{big}"""',
            'def main(): Path("outputs").mkdir(exist_ok=True)',
            'if __name__ == "__main__": main()',
        ]
    )
    errs = validate_script(code)
    assert any("过长字符串" in e for e in errs)
