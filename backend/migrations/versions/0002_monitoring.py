"""Article inspection, engine synchronization and independent error states."""
from alembic import op
from sqlalchemy import Column, Float, Integer, Text, String, ForeignKey

revision = '0002_monitoring'
down_revision = '0001_server'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('monitor_states',
        Column('article_id', String(100), ForeignKey('articles.id'), primary_key=True),
        Column('next_inspect', Float, nullable=False), Column('next_sync', Float, nullable=False),
        Column('last_inspect', Float), Column('last_sync', Float),
        Column('inspect_error', Text, nullable=False), Column('sync_error', Text, nullable=False),
        Column('engine_paused', Integer), Column('rebase_after', Float), Column('history_cursor', Float))


def downgrade():
    raise RuntimeError('Restore a verified backup instead of deleting monitoring state')
