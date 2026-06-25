"""merge meeting_minutes + work_orders heads (integrate-all)

Revision ID: be2ac347ccbb
Revises: 2026_06_24_meeting_minutes, 2026_06_24_work_orders
Create Date: 2026-06-25 18:50:51.395923

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be2ac347ccbb'
down_revision: Union[str, Sequence[str], None] = ('2026_06_24_meeting_minutes', '2026_06_24_work_orders')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
