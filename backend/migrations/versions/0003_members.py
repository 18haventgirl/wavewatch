"""Invite-only WeChat identities, hashed sessions and personal preferences."""
from alembic import op
import sqlalchemy as sa

revision = '0003_members'
down_revision = '0002_monitoring'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('wechat_identities',
        sa.Column('appid', sa.String(32), primary_key=True), sa.Column('openid', sa.String(128), primary_key=True),
        sa.Column('user_id', sa.String(100), sa.ForeignKey('users.id'), nullable=False), sa.Column('created', sa.Float, nullable=False))
    op.create_table('sessions', sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(100), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created', sa.Float, nullable=False), sa.Column('expires', sa.Float, nullable=False),
        sa.Column('revoked', sa.Integer, nullable=False))
    op.create_table('invitations', sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('role', sa.String(32), nullable=False),
        sa.Column('target_user_id', sa.String(100), sa.ForeignKey('users.id')),
        sa.Column('created_by', sa.String(100), sa.ForeignKey('users.id')),
        sa.Column('created', sa.Float, nullable=False), sa.Column('expires', sa.Float, nullable=False),
        sa.Column('used_by', sa.String(100), sa.ForeignKey('users.id')), sa.Column('used_at', sa.Float),
        sa.Column('revoked', sa.Integer, nullable=False), sa.CheckConstraint("role IN ('admin','member')", name='invitation_role'))
    op.create_table('login_codes', sa.Column('code_hash', sa.String(64), primary_key=True),
                    sa.Column('created', sa.Float, nullable=False))
    op.create_table('auth_buckets', sa.Column('id', sa.String(64), primary_key=True),
                    sa.Column('window', sa.Float, nullable=False), sa.Column('count', sa.Integer, nullable=False))
    op.create_table('preferences', sa.Column('user_id', sa.String(100), sa.ForeignKey('users.id'), primary_key=True),
                    sa.Column('config', sa.JSON, nullable=False), sa.Column('updated', sa.Float, nullable=False))
    op.create_table('favorites', sa.Column('user_id', sa.String(100), sa.ForeignKey('users.id'), primary_key=True),
                    sa.Column('article_id', sa.String(100), sa.ForeignKey('articles.id'), primary_key=True),
                    sa.Column('created', sa.Float, nullable=False))


def downgrade():
    raise RuntimeError('Restore a verified backup instead of deleting member data')
