from __future__ import annotations

import pandas as pd
import pytest

from app.application.tools.safe_dataframe_query import safe_filter_dataframe


def test_filters_with_comparisons_boolean_operators_and_membership() -> None:
    frame = pd.DataFrame(
        {
            "qty": [1, 2, 3],
            "region": ["east", "west", "east"],
            "enabled": [True, True, False],
        }
    )

    result = safe_filter_dataframe(
        frame,
        "qty >= 2 and region in ['east', 'west'] and not enabled == False",
    )

    assert result.to_dict(orient="records") == [{"qty": 2, "region": "west", "enabled": True}]


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "qty.__class__",
        "qty[0]",
        "[item for item in qty]",
        "open('/etc/passwd')",
    ],
)
def test_rejects_executable_or_introspective_constructs(expression: str) -> None:
    frame = pd.DataFrame({"qty": [1, 2, 3]})

    with pytest.raises(ValueError, match="unsupported"):
        safe_filter_dataframe(frame, expression)


def test_requires_boolean_result_and_known_column() -> None:
    frame = pd.DataFrame({"qty": [1, 2, 3]})

    with pytest.raises(ValueError, match="boolean filter"):
        safe_filter_dataframe(frame, "qty + 1")
    with pytest.raises(ValueError, match="unknown dataframe column"):
        safe_filter_dataframe(frame, "missing > 1")
