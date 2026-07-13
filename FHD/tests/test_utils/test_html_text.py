from app.utils.html_text import html_to_plain_text


def test_html_to_plain_text_handles_markup_without_regex_backtracking() -> None:
    assert html_to_plain_text("<p>甲&lt;乙<br/>第二行</p>") == "甲<乙\n第二行"


def test_html_to_plain_text_bounds_untrusted_input() -> None:
    assert html_to_plain_text("a" * 20, max_chars=5) == "a" * 5
