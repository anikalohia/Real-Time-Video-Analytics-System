"""Initial schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'streams',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='stopped'),
        sa.Column('health', sa.String(50), nullable=False, server_default='stopped'),
        sa.Column('target_fps', sa.Integer(), server_default='10'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        'events',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('stream_id', sa.Uuid(), nullable=True),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=True),
        sa.Column('class', sa.String(100), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('bbox', sa.JSON(), nullable=True),
        sa.Column('track_id', sa.String(50), nullable=True),
        sa.Column('frame_id', sa.Integer(), nullable=True),
    )
    op.create_index('ix_events_stream_ts', 'events', ['stream_id', sa.text('ts DESC')])
    op.create_index('ix_events_class_ts', 'events', ['class', sa.text('ts DESC')])
    op.create_index('ix_events_ts', 'events', [sa.text('ts DESC')])

    op.create_table(
        'rules',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('stream_id', sa.Uuid(), nullable=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('class_filter', sa.String(100), nullable=True),
        sa.Column('zone_polygon', sa.JSON(), nullable=True),
        sa.Column('threshold_count', sa.Integer(), server_default='1'),
        sa.Column('dwell_seconds', sa.Integer(), server_default='0'),
        sa.Column('cooldown_seconds', sa.Integer(), server_default='60'),
        sa.Column('webhook_url', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), server_default=sa.true()),
    )
    op.create_index('ix_rules_stream', 'rules', ['stream_id'])

    op.create_table(
        'alerts',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('rule_id', sa.Uuid(), nullable=True),
        sa.Column('stream_id', sa.Uuid(), nullable=True),
        sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('delivered', sa.Boolean(), server_default=sa.false()),
    )
    op.create_index('ix_alerts_ts', 'alerts', [sa.text('ts DESC')])

    op.create_table(
        'users',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), server_default='operator'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('users')
    op.drop_index('ix_alerts_ts', table_name='alerts')
    op.drop_table('alerts')
    op.drop_index('ix_rules_stream', table_name='rules')
    op.drop_table('rules')
    op.drop_index('ix_events_ts', table_name='events')
    op.drop_index('ix_events_class_ts', table_name='events')
    op.drop_index('ix_events_stream_ts', table_name='events')
    op.drop_table('events')
    op.drop_table('streams')
