from datetime import datetime, timezone
from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class Corpus(Base):
    __tablename__ = 'corpora'
    corpus_id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(default=1)
    name: Mapped[str]
    description: Mapped[str] = mapped_column(default='')
    builtin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[str] = mapped_column(default=now)


class CorpusArchive(Base):
    __tablename__ = 'corpus_archives'
    corpus_id: Mapped[str] = mapped_column(ForeignKey('corpora.corpus_id'), primary_key=True)
    created_at: Mapped[str] = mapped_column(default=now)


class BuiltinExclusion(Base):
    """Only a source identifier: prevent deleted bundled data from being reimported."""
    __tablename__ = 'builtin_exclusions'
    source_id: Mapped[str] = mapped_column(String, primary_key=True)


class PendingDeletion(Base):
    """Durable cleanup intent across SQLite, vector storage and original files."""
    __tablename__ = 'pending_deletions'
    target_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str]


class Resource(Base):
    __tablename__ = 'resources'
    resource_id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(default=1)
    resource_kind: Mapped[str] = mapped_column(default='monologue')
    system_tags: Mapped[list] = mapped_column(JSON, default=lambda: ['imported_text'])
    title: Mapped[str]
    source_type: Mapped[str] = mapped_column(default='upload')
    source_ref_id: Mapped[str]
    content_hash: Mapped[str]
    visibility: Mapped[str] = mapped_column(default='active')
    version_id: Mapped[str]
    active_generation: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[str] = mapped_column(default=now)
    meta: Mapped[dict] = mapped_column('metadata', JSON, default=dict)


class CorpusResource(Base):
    __tablename__ = 'corpus_resources'
    corpus_id: Mapped[str] = mapped_column(ForeignKey('corpora.corpus_id'), primary_key=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey('resources.resource_id'), primary_key=True)


class ResourceVersion(Base):
    __tablename__ = 'resource_versions'
    version_id: Mapped[str] = mapped_column(String, primary_key=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey('resources.resource_id'), index=True)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str]
    parser_version: Mapped[str] = mapped_column(default='structured-text-v1')
    created_at: Mapped[str] = mapped_column(default=now)


class Fragment(Base):
    __tablename__ = 'fragments'
    fragment_id: Mapped[str] = mapped_column(String, primary_key=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey('resources.resource_id'), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey('resource_versions.version_id'), index=True)
    fragment_index: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int]
    end_offset: Mapped[int]
    citation: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint('version_id', 'fragment_index'),)


class IngestionJob(Base):
    __tablename__ = 'ingestion_jobs'
    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey('resources.resource_id'), index=True)
    version_id: Mapped[str]
    status: Mapped[str] = mapped_column(default='pending')
    processed: Mapped[int] = mapped_column(default=0)
    total: Mapped[int] = mapped_column(default=0)
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    model: Mapped[str]
    created_at: Mapped[str] = mapped_column(default=now)

