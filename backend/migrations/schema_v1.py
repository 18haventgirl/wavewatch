"""Frozen schema for revision 0001. Add future changes in new revisions."""
from sqlalchemy import (MetaData, Table, Column as C, String as S, Text, Integer as I,
                        Float as F, JSON, ForeignKey as FK, UniqueConstraint as U, Index, CheckConstraint)

metadata = MetaData()


def table(name, *columns):
    return Table(name, metadata, *columns)


countries = table('countries', C('code', S(8), primary_key=True), C('name', Text, nullable=False, unique=True))
publishers = table('publishers', C('id', S(100), primary_key=True), C('country_code', FK('countries.code'), nullable=False), C('name', Text, nullable=False), C('homepage', Text, nullable=False))
data_scopes = table('data_scopes', C('id', S(100), primary_key=True), C('country_code', FK('countries.code'), nullable=False), C('publisher_id', FK('publishers.id'), nullable=False), C('name', Text, nullable=False), C('created', F, nullable=False))
categories = table('categories', C('id', S(100), primary_key=True), C('publisher_id', FK('publishers.id'), nullable=False), C('parent_id', FK('categories.id')), C('name', Text, nullable=False), C('external_code', S(100)), C('position', I, nullable=False, default=0), U('publisher_id', 'external_code'))
sources = table('sources', C('id', S(100), primary_key=True), C('config', JSON, nullable=False), C('publisher_id', FK('publishers.id')), C('category_id', FK('categories.id')), C('scope_id', FK('data_scopes.id')), C('name', Text), C('in_scope', I, nullable=False, default=1), C('paused', I, nullable=False, default=0), C('hours', I, nullable=False, default=6), C('state', S(32), nullable=False, default='pending'), C('error', Text, nullable=False, default=''), C('last_check', F), C('last_success', F), C('next_check', F, nullable=False, default=0), C('initialized', I, nullable=False, default=0), C('coverage', Text, nullable=False, default='尚未建立基线'))
articles = table('articles', C('id', S(100), primary_key=True), C('origin_source_id', FK('sources.id'), nullable=False), C('url', Text, nullable=False, unique=True), C('title', Text, nullable=False), C('published', Text), C('subtitle', Text, nullable=False, default=''), C('description', Text, nullable=False, default=''), C('discovered', F, nullable=False), C('watch_id', S(100)), C('kind', S(32), nullable=False, default='article'), C('parent_id', S(100)), C('error', Text, nullable=False, default=''))
article_sources = table('article_sources', C('article_id', FK('articles.id'), primary_key=True), C('source_id', FK('sources.id'), primary_key=True), C('first_seen', F, nullable=False), C('last_seen', F, nullable=False), C('external_key', Text), C('source_page', I))
source_entries = table('source_entries', C('source_id', FK('sources.id'), primary_key=True), C('external_key', Text, primary_key=True), C('article_id', FK('articles.id'), nullable=False), C('source_page', I), C('source_position', I), C('raw_title', Text), C('first_seen', F, nullable=False), C('last_seen', F, nullable=False))
article_attachments = table('article_attachments', C('parent_id', FK('articles.id'), primary_key=True), C('attachment_id', FK('articles.id'), primary_key=True), C('first_seen', F, nullable=False))
versions = table('versions', C('id', I, primary_key=True), C('article_id', FK('articles.id'), nullable=False), C('stamp', Text, nullable=False), C('content', Text, nullable=False), C('digest', S(64), nullable=False), C('created', F, nullable=False), U('article_id', 'stamp'))
events = table('events', C('id', S(250), primary_key=True), C('article_id', FK('articles.id'), nullable=False), C('kind', S(32), nullable=False), C('created', F, nullable=False), C('unread', I, nullable=False, default=1), C('version_id', FK('versions.id')))
runs = table('runs', C('id', I, primary_key=True), C('source_id', FK('sources.id'), nullable=False), C('started', F, nullable=False), C('finished', F), C('state', S(32), nullable=False), C('count', I, nullable=False, default=0), C('message', Text, nullable=False, default=''), C('details', JSON))
crawl_pages = table('crawl_pages', C('id', I, primary_key=True), C('run_id', FK('runs.id'), nullable=False), C('source_id', FK('sources.id'), nullable=False), C('page_number', I, nullable=False), C('item_count', I, nullable=False), C('reported_total', I), C('response_digest', S(64), nullable=False), C('checked', F, nullable=False), U('run_id', 'page_number'))
legacy_metadata = table('metadata', C('key', Text, primary_key=True), C('value', Text, nullable=False))
file_checks = table('file_checks', C('article_id', FK('articles.id'), primary_key=True), C('checked', F, nullable=False))
file_blobs = table('file_blobs', C('digest', S(64), primary_key=True), C('path', Text, nullable=False), C('bytes', I, nullable=False))
file_versions = table('file_versions', C('version_id', FK('versions.id'), primary_key=True), C('blob_digest', FK('file_blobs.digest'), nullable=False))
users = table('users', C('id', S(100), primary_key=True), C('name', Text, nullable=False), C('role', S(32), nullable=False), C('active', I, nullable=False, default=1), C('created', F, nullable=False))
user_event_states = table('user_event_states', C('user_id', FK('users.id'), primary_key=True), C('event_id', FK('events.id'), primary_key=True), C('read_at', F))
jobs = table('jobs', C('id', S(64), primary_key=True), C('dedup_key', S(250), nullable=False, unique=True), C('resource_key', S(150), nullable=False), C('kind', S(50), nullable=False), C('payload', JSON, nullable=False), C('state', S(20), nullable=False, default='ready'), C('due', F, nullable=False), C('attempts', I, nullable=False, default=0), C('lease_token', S(64)), C('lease_until', F), C('created', F, nullable=False), C('finished', F), C('error', Text, nullable=False, default=''))
Index('jobs_due', jobs.c.state, jobs.c.due)
Index('article_sources_source', article_sources.c.source_id, article_sources.c.article_id)
Index('source_entries_position', source_entries.c.source_id, source_entries.c.source_position)
Index('versions_article', versions.c.article_id, versions.c.id)
Index('events_article', events.c.article_id, events.c.created)
sources.append_constraint(CheckConstraint('in_scope = 0 OR scope_id IS NOT NULL', name='active_source_requires_scope'))
sources.append_constraint(CheckConstraint('hours >= 1 AND hours <= 168', name='source_interval_range'))
jobs.append_constraint(CheckConstraint("state IN ('ready','leased','done','dead')", name='job_state'))
jobs.append_constraint(CheckConstraint('attempts >= 0', name='job_attempts'))
