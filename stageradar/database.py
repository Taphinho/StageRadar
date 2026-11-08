from datetime import date, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, ForeignKey, UniqueConstraint, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.types import JSON

from stageradar.schemas import Status, utc_now
from stageradar.scoring import normalize

ROOT = Path(__file__).resolve().parent.parent


class Base(DeclarativeBase):
    pass


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    employer_key: Mapped[str] = mapped_column(index=True)
    employer: Mapped[str]
    title: Mapped[str]
    search_text: Mapped[str]
    first_seen: Mapped[datetime] = mapped_column(default=utc_now, index=True)
    last_seen: Mapped[datetime] = mapped_column(default=utc_now)
    published_at: Mapped[datetime | None]
    expired: Mapped[bool] = mapped_column(default=False)
    details: Mapped[dict] = mapped_column(JSON)
    score: Mapped[int] = mapped_column(index=True)
    reasons: Mapped[list[dict]] = mapped_column(JSON)
    domains: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(default=Status.REVIEW)
    favorite: Mapped[bool] = mapped_column(default=False)
    hidden: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str] = mapped_column(default="")
    applied_on: Mapped[date | None]
    reminder_on: Mapped[date | None]
    listings: Mapped[list["Listing"]] = relationship(back_populates="offer")


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source", "source_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), index=True)
    offer: Mapped[Offer] = relationship(back_populates="listings")
    source: Mapped[str]
    source_key: Mapped[str]
    canonical: Mapped[str] = mapped_column(index=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str]
    first_seen: Mapped[datetime] = mapped_column(default=utc_now)
    last_seen: Mapped[datetime] = mapped_column(default=utc_now)
    closed_at: Mapped[datetime | None]
    misses: Mapped[int] = mapped_column(default=0)


class Revision(Base):
    __tablename__ = "revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(default=utc_now)
    snapshot: Mapped[dict] = mapped_column(JSON)


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(index=True)
    started_at: Mapped[datetime] = mapped_column(default=utc_now, index=True)
    finished_at: Mapped[datetime | None]
    retry_at: Mapped[datetime | None]
    status: Mapped[str]
    error: Mapped[str | None]
    fetched: Mapped[int] = mapped_column(default=0)
    created: Mapped[int] = mapped_column(default=0)
    updated: Mapped[int] = mapped_column(default=0)
    skipped: Mapped[int] = mapped_column(default=0)


class Notification(Base):
    __tablename__ = "notifications"

    key: Mapped[str] = mapped_column(primary_key=True)
    offer_id: Mapped[int | None] = mapped_column(ForeignKey("offers.id"))
    body: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt: Mapped[datetime] = mapped_column(default=utc_now, index=True)
    delivered_at: Mapped[datetime | None]


def open_database(data_dir: Path) -> Engine:
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(URL.create("sqlite", database=str(data_dir / "stageradar.sqlite3")))

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record) -> None:
        connection.create_function(
            "normalize_text", 1, lambda value: normalize(value or ""), deterministic=True
        )
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    return engine


def upgrade(engine: Engine) -> None:
    config = Config()
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(engine, expire_on_commit=False)
