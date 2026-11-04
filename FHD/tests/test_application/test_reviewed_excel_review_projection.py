"""Pure reviewed-Excel review projections and lineage policy regressions."""

from __future__ import annotations

import pytest

from app.application.reviewed_excel_review_projection import (
    TEST_ONLY_RESTRICTION,
    build_candidate_previews,
    compose_usage_restrictions,
)


def test_candidate_preview_uses_cleaned_bytes_and_preserves_order():
    cleaning = []
    inspected = []

    def clean(body, source_sha, clear):
        cleaning.append((body, source_sha, clear))
        return ("clean:" + clear).encode()

    def inspect(body):
        inspected.append(body)
        return {
            "sha256": body.decode(),
            "layout": [body.decode()],
            "layout_truncated": False,
        }

    proposal = {"candidates": [{"id": "first", "clear": "A"}, {"id": "second", "clear": "B"}]}
    result = build_candidate_previews(
        b"raw",
        {"sha256": "source-sha"},
        proposal,
        clean_workbook=clean,
        inspect_workbook=inspect,
    )
    assert result is None
    assert cleaning == [(b"raw", "source-sha", "A"), (b"raw", "source-sha", "B")]
    assert inspected == [b"clean:A", b"clean:B"]
    assert proposal["result_previews"] == [
        {
            "candidate_id": "first",
            "sha256": "clean:A",
            "layout": ["clean:A"],
            "layout_truncated": False,
        },
        {
            "candidate_id": "second",
            "sha256": "clean:B",
            "layout": ["clean:B"],
            "layout_truncated": False,
        },
    ]


def test_candidate_preview_does_not_swallow_cleaner_failure():
    def fail_clean(*args):
        raise ValueError("unsafe range")

    with pytest.raises(ValueError, match="unsafe range"):
        build_candidate_previews(
            b"raw",
            {"sha256": "sha"},
            {"candidates": [{"id": "bad", "clear": []}]},
            clean_workbook=fail_clean,
            inspect_workbook=lambda _data: {},
        )


def test_candidate_preview_empty_candidates_yield_empty_result():
    proposal = {"candidates": []}
    build_candidate_previews(
        b"",
        {"sha256": "source"},
        proposal,
        clean_workbook=lambda *args: b"",
        inspect_workbook=lambda data: {},
    )
    assert proposal["result_previews"] == []


@pytest.mark.parametrize(
    ("summary", "inherited", "expected"),
    [
        ({}, [], []),
        ({"usage_restrictions": ["A", "A", "B"]}, ["B", "C"], ["A", "B", "C"]),
        (
            {"conversion_receipt": {"purpose": "data_template_test_only"}},
            [],
            [TEST_ONLY_RESTRICTION],
        ),
        (
            {
                "usage_restrictions": ["original", TEST_ONLY_RESTRICTION],
                "conversion_receipt": {"purpose": "data_template_test_only"},
            },
            [TEST_ONLY_RESTRICTION, "inherited"],
            ["original", TEST_ONLY_RESTRICTION, "inherited"],
        ),
        (
            {"conversion_receipt": {"purpose": "normal"}},
            ["source"],
            ["source"],
        ),
    ],
)
def test_usage_restrictions_order_and_lineage(summary, inherited, expected):
    assert compose_usage_restrictions(summary, inherited) == expected
