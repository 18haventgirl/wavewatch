from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlalchemy.engine import make_url
from alembic import command
from alembic.config import Config
from backend.schema import metadata

ROOT = Path(__file__).resolve().parents[1]
CURRENT_REVISION = '0002_monitoring'
tables = metadata.tables


def make_engine(url):
    options = {'pool_pre_ping': True}
    parsed = make_url(url)
    if parsed.get_backend_name() == 'sqlite':
        options['connect_args'] = {'check_same_thread': False, 'timeout': 30}
        if parsed.database in (None, '', ':memory:'):
            options['poolclass'] = StaticPool
    engine = create_engine(url, **options)
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
    return engine


def migrate(engine):
    config = Config()
    config.set_main_option('script_location', str(ROOT / 'backend' / 'migrations'))
    with engine.begin() as conn:
        config.attributes['connection'] = conn
        command.upgrade(config, 'head')


def insert_ignore(conn, table, values, keys, returning=None):
    if conn.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    statement = insert(table).values(**values).on_conflict_do_nothing(index_elements=keys)
    if returning is not None:
        statement = statement.returning(returning)
    return conn.execute(statement)
