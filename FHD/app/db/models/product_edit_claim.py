"""Durable fence for a reviewed product edit; no business data is stored here."""

from sqlalchemy import Index, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ProductEditClaimBase(DeclarativeBase):
    """Private HOST claim metadata. Not part of the owned catalog or startup Base."""


class ProductEditClaimRecord(ProductEditClaimBase):
    __tablename__ = "agent_product_edit_claims"
    __table_args__ = (
        Index(
            "ix_product_edit_claim_owner_product", "tenant_id", "user_id", "mod_id", "product_id"
        ),
    )

    # The resource key excludes the owner: another user must not silently
    # overwrite a product while an earlier owner's outcome is unresolved.
    resource_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mod_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_id: Mapped[str] = mapped_column(String(32), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(String(48), nullable=False)


def validate_product_edit_claim_schema(connection):
    """Validation only: no preparation, restamp, alteration or retention cleanup."""
    import re

    from sqlalchemy.schema import CreateIndex, CreateTable

    if connection.dialect.name != "sqlite":
        raise RuntimeError("owned product claim schema requires SQLite")
    table = ProductEditClaimRecord.__table__
    compact = lambda value: re.sub(r"\s+", "", str(value or "")).lower()
    expected = {
        ("table", table.name): compact(CreateTable(table).compile(dialect=connection.dialect))
    }
    expected.update(
        {
            ("index", index.name): compact(CreateIndex(index).compile(dialect=connection.dialect))
            for index in table.indexes
        }
    )
    actual = {
        (kind, name): compact(sql)
        for kind, name, sql in connection.exec_driver_sql(
            "SELECT type,name,sql FROM main.sqlite_master WHERE tbl_name=? AND sql IS NOT NULL",
            (table.name,),
        )
    }
    shadow = connection.exec_driver_sql(
        "SELECT 1 FROM temp.sqlite_master WHERE name=? OR tbl_name=? LIMIT 1",
        (table.name, table.name),
    ).first()
    if actual != expected or shadow:
        raise RuntimeError("owned product claim schema requires migration review")
