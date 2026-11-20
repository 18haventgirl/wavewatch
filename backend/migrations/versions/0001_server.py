"""Server foundation and durable jobs, imported from SQLite v5."""
from alembic import op
from backend.migrations.schema_v1 import metadata

revision = '0001_server'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind())


def downgrade():
    raise RuntimeError('Destructive downgrade is disabled; restore the verified backup instead')
