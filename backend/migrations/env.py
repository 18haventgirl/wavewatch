from alembic import context
from backend.schema import metadata

connection = context.config.attributes.get('connection')
if connection is None:
    raise RuntimeError('Use python -m backend.cli migrate; database credentials stay outside alembic.ini')
context.configure(connection=connection, target_metadata=metadata)
with context.begin_transaction():
    context.run_migrations()
