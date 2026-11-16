"""Raw SQL scanner regressions."""

from scripts.dev.count_raw_sql import FSQL_PATTERN


def test_pdf_suffix_delete_keyword_is_not_fstring_sql():
    source = 'with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:'
    assert FSQL_PATTERN.search(source) is None


def test_actual_fstring_sql_is_still_detected():
    assert FSQL_PATTERN.search('query = f"SELECT * FROM records WHERE id = {record_id}"')
