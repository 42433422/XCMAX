from __future__ import annotations

import pytest

from modstore_server.html_text import html_to_plain_text


@pytest.mark.parametrize(
    "closing_tag",
    ["</script>", "</script >", "</SCRIPT   >"],
)
def test_html_to_plain_text_drops_script_content_with_tag_whitespace(closing_tag):
    html = f"<p>Visible</p><script>alert('secret'){closing_tag}<b>After</b>"

    assert html_to_plain_text(html) == "Visible After"


def test_html_to_plain_text_drops_styles_and_decodes_entities():
    html = "<style>body { display: none }</style><p>A &amp; B</p>"

    assert html_to_plain_text(html) == "A & B"
