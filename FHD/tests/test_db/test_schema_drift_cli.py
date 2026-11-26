"""Real Alembic and SQLite parity: CI and the local CLI use the same env."""

import os
import sys

import pytest

from scripts.dev import check_schema_drift


@pytest.mark.parametrize("expected", [0, 1, 2])
def test_schema_drift_uses_canonical_environment(tmp_path, monkeypatch, capsys, expected):
    scripts = tmp_path / "alembic"
    versions = scripts / "versions"
    versions.mkdir(parents=True)
    (tmp_path / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    column = 'sa.Column("extra", sa.Integer),' if expected == 1 else ""
    (scripts / "env.py").write_text(
        f"""import os
import sqlalchemy as sa
from alembic import context
metadata = sa.MetaData()
sa.Table("owned", metadata, sa.Column("id", sa.Integer, primary_key=True), {column})
engine = sa.create_engine(os.environ["DATABASE_URL"])
with engine.connect() as conn:
    context.configure(connection=conn, target_metadata=metadata,
                      include_name=lambda name, kind, parents: name != "agent_business_actions")
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
""",
        encoding="utf-8",
    )
    failure = '    raise RuntimeError("migration failure")\n' if expected == 2 else ""
    (versions / "baseline.py").write_text(
        f"""import sqlalchemy as sa
from alembic import op
revision = "baseline"
down_revision = None
def upgrade():
{failure}    op.create_table("owned", sa.Column("id", sa.Integer, primary_key=True))
    op.create_table("agent_business_actions", sa.Column("id", sa.Integer, primary_key=True))
""",
        encoding="utf-8",
    )
    original = tmp_path / "untouched.db"
    original_url = f"sqlite:///{original.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", original_url)
    monkeypatch.setattr(check_schema_drift, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_schema_drift.py"])
    assert check_schema_drift.main() == expected
    assert os.environ["DATABASE_URL"] == original_url
    assert not original.exists()
    output = capsys.readouterr().out
    if expected == 0:
        assert "[schema-drift] PASS" in output
    elif expected == 1:
        assert "[schema-drift] FAIL" in output and "extra" in output
    else:
        assert "非漂移结论" in output
