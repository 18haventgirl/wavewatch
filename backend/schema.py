"""Current schema. Historical revisions keep their own frozen definitions."""
from sqlalchemy import Table, Column, Float, Integer, Text, String, ForeignKey, MetaData
from backend.migrations.schema_v1 import metadata as baseline

metadata = MetaData()
for frozen_table in baseline.sorted_tables:
    frozen_table.to_metadata(metadata)

monitor_states = Table('monitor_states', metadata,
    Column('article_id', String(100), ForeignKey('articles.id'), primary_key=True),
    Column('next_inspect', Float, nullable=False, default=0),
    Column('next_sync', Float, nullable=False, default=0),
    Column('last_inspect', Float), Column('last_sync', Float),
    Column('inspect_error', Text, nullable=False, default=''),
    Column('sync_error', Text, nullable=False, default=''),
    Column('engine_paused', Integer), Column('rebase_after', Float), Column('history_cursor', Float))
