"""Current schema. Historical revisions keep their own frozen definitions."""
from sqlalchemy import Table, Column, Float, Integer, Text, String, ForeignKey, MetaData, JSON, CheckConstraint
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

wechat_identities = Table('wechat_identities', metadata,
    Column('appid', String(32), primary_key=True), Column('openid', String(128), primary_key=True),
    Column('user_id', ForeignKey('users.id'), nullable=False), Column('created', Float, nullable=False))
sessions = Table('sessions', metadata,
    Column('token_hash', String(64), primary_key=True), Column('user_id', ForeignKey('users.id'), nullable=False),
    Column('created', Float, nullable=False), Column('expires', Float, nullable=False),
    Column('revoked', Integer, nullable=False, default=0))
invitations = Table('invitations', metadata,
    Column('token_hash', String(64), primary_key=True), Column('role', String(32), nullable=False),
    Column('target_user_id', ForeignKey('users.id')), Column('created_by', ForeignKey('users.id')),
    Column('created', Float, nullable=False), Column('expires', Float, nullable=False),
    Column('used_by', ForeignKey('users.id')), Column('used_at', Float),
    Column('revoked', Integer, nullable=False, default=0),
    CheckConstraint("role IN ('admin', 'member')", name='invitation_role'))
login_codes = Table('login_codes', metadata,
    Column('code_hash', String(64), primary_key=True), Column('created', Float, nullable=False))
auth_buckets = Table('auth_buckets', metadata,
    Column('id', String(64), primary_key=True), Column('window', Float, nullable=False),
    Column('count', Integer, nullable=False, default=0))
preferences = Table('preferences', metadata, Column('user_id', ForeignKey('users.id'), primary_key=True),
    Column('config', JSON, nullable=False), Column('updated', Float, nullable=False))
favorites = Table('favorites', metadata, Column('user_id', ForeignKey('users.id'), primary_key=True),
    Column('article_id', ForeignKey('articles.id'), primary_key=True), Column('created', Float, nullable=False))
