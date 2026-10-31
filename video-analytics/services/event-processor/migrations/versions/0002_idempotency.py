"""Add idempotency keys for events and alerts.

Revision ID: 0002_idempotency
Revises: 0001_initial
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002_idempotency'
down_revision: str | None = '0001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('events', sa.Column('event_key', sa.String(255), nullable=True))
    op.create_index('ux_events_event_key', 'events', ['event_key'], unique=True)
    op.add_column('alerts', sa.Column('alert_key', sa.String(255), nullable=True))
    op.create_index('ux_alerts_alert_key', 'alerts', ['alert_key'], unique=True)


def downgrade() -> None:
    op.drop_index('ux_alerts_alert_key', table_name='alerts')
    op.drop_column('alerts', 'alert_key')
    op.drop_index('ux_events_event_key', table_name='events')
    op.drop_column('events', 'event_key')
