"""Privacy parsing tests use real YAML nodes, independently of the browser driver."""

import pytest
import yaml

from app.infrastructure.browser.snapshot import redact_snapshot


def test_editable_values_are_removed_but_role_and_locator_labels_survive():
    snapshot = """- 'textbox "API: token"': "credential: [one]\\nsecond line"
- textbox "Notes": |
    line one secret
    line two secret
- combobox "Account":
  - option "secret account" [selected]
- paragraph: "credential: [one] second line"
- text: 00123
- button "Continue"
"""
    result = redact_snapshot(snapshot, ["credential: [one]\nsecond line", "00123"])
    assert (
        "credential" not in result
        and "line one secret" not in result
        and "secret account" not in result
    )
    assert "00123" not in result
    tree = yaml.safe_load(result)
    assert tree[0] == {'textbox "API: token"': "[redacted]"}
    assert tree[1] == {'textbox "Notes"': "[redacted]"}
    assert tree[2] == {'combobox "Account"': "[redacted]"}
    assert tree[-1] == 'button "Continue"'


def test_contenteditable_fragments_and_echoed_values_are_redacted_without_replacing_tokens_twice():
    snapshot = """- generic "Rich notes":
  - paragraph: "private fragment"
  - text: "another fragment"
- button "Save"
"""
    result = redact_snapshot(
        snapshot,
        ["private fragmentanother fragment", "private fragment", "another fragment", "redacted"],
    )
    assert "private fragment" not in result and "another fragment" not in result
    assert result.count("[redacted]") == 2 and 'button "Save"' in result


def test_editable_role_branches_are_masked_even_without_a_stable_collected_value():
    result = redact_snapshot('- textbox "Token": changed-after-inspection\n- paragraph: public', [])
    assert "changed-after-inspection" not in result
    assert "public" in result and 'textbox "Token"' in result


@pytest.mark.parametrize(
    "snapshot,values",
    [
        ("- [malformed", []),
        ("- &cycle [*cycle]", []),
        ("- text: " + "x" * 120_000, []),
        ("- paragraph: public", ["x"] * 2_001),
        ("- paragraph: public", ["x" * 131_073]),
        ("- paragraph: public", [None]),
    ],
)
def test_uninspectable_or_oversized_snapshot_fails_closed(snapshot, values):
    with pytest.raises(ValueError, match="browser_snapshot_privacy"):
        redact_snapshot(snapshot, values)


def test_yaml_tags_are_never_constructed_as_page_supplied_objects():
    result = redact_snapshot('!!python/object/apply:os.system ["synthetic text"]', [])
    assert yaml.safe_load(result) == ["synthetic text"]
    assert "!!python" not in result


def test_receipt_url_omits_redirect_tokens_but_retains_document_path():
    from app.infrastructure.browser.runtime import _receipt_url

    assert _receipt_url(
        "https://allowed.example/finish?code=synthetic-token#access_token=secret"
    ) == ("https://allowed.example/finish")
