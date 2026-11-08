import asyncio
import logging
from datetime import timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from stageradar.collectors.base import Collector, SourceError
from stageradar.config import Settings
from stageradar.database import CollectionRun, Listing, Offer
from stageradar.offers import ingest, plain_text, refresh_offer
from stageradar.schemas import MANUAL_SOURCES, ListingInput, utc_now
from stageradar.scoring import is_internship

LOG = logging.getLogger(__name__)


def latest_run(db: Session, source: str, statuses: tuple[str, ...] = ()) -> CollectionRun | None:
    stmt = select(CollectionRun).where(CollectionRun.source == source)
    if statuses:
        stmt = stmt.where(CollectionRun.status.in_(statuses))
    return db.scalar(stmt.order_by(CollectionRun.id.desc()).limit(1))


def source_states(db: Session, collectors: list[Collector], settings: Settings) -> list[dict]:
    active_counts = dict(
        db.execute(
            select(Listing.source, func.count(func.distinct(Listing.offer_id)))
            .where(Listing.closed_at.is_(None))
            .group_by(Listing.source)
        ).all()
    )
    visible_counts = dict(
        db.execute(
            select(Listing.source, func.count(func.distinct(Listing.offer_id)))
            .join(Offer)
            .where(Listing.closed_at.is_(None), ~Offer.hidden, ~Offer.expired)
            .group_by(Listing.source)
        ).all()
    )
    states = []
    for collector in collectors:
        last = latest_run(db, collector.key)
        success = latest_run(db, collector.key, ("ok", "partial"))
        interval = max(settings.collect_minutes, getattr(collector, "min_interval_minutes", 0))
        stale = bool(success and success.finished_at < utc_now() - timedelta(minutes=interval * 2))
        health = "unavailable"
        if last and last.status == "ok":
            health = "operational"
        elif last and (last.status == "partial" or success):
            health = "degraded"
        if stale:
            health = "degraded"
        employers = [collector.label]
        if collector.key == "successfactors:atos":
            employers.append("Eviden")
        elif collector.key == "teamtailor:vinci-energies":
            employers.append("Axians")
        elif collector.key == "orangejobs:fr":
            employers.extend(["Orange", "Orange Cyberdefense"])
        states.append(
            {
                "key": collector.key,
                "label": collector.label,
                "employers": employers,
                "mode": "automatic",
                "health": health,
                "last_status": last.status if last else "waiting",
                "last_success": success.finished_at.isoformat() + "Z" if success else None,
                "last_attempt": last.started_at.isoformat() + "Z" if last else None,
                "stale": stale,
                "retry_at": last.retry_at.isoformat() + "Z" if last and last.retry_at else None,
                "fetched": last.fetched if last else 0,
                "active_offers": active_counts.get(collector.key, 0),
                "visible_offers": visible_counts.get(collector.key, 0),
                "skipped": last.skipped if last else 0,
                "error": last.error if last else None,
                "interval_minutes": interval,
            }
        )
    for key, label in MANUAL_SOURCES.items():
        states.append(
            {"key": f"manual:{key}", "label": label, "mode": "manual", "health": "unconfigured"}
        )
    return states


class Collection:
    def __init__(
        self,
        sessions: sessionmaker,
        collectors: list[Collector],
        settings: Settings,
        client: httpx.AsyncClient,
    ) -> None:
        self.sessions = sessions
        self.collectors = collectors
        self.settings = settings
        self.client = client
        self.lock = asyncio.Lock()
        self.progress = {
            "running": False,
            "total": 0,
            "completed": 0,
            "current": None,
            "fetched": 0,
            "created": 0,
            "updated": 0,
            "results": [],
        }

    async def run(self, *, force: bool = False, sources: list[str] | None = None) -> list[dict]:
        if self.lock.locked():
            return []
        async with self.lock:
            collectors = [
                item for item in self.collectors if sources is None or item.key in sources
            ]
            self.progress = {
                "running": True,
                "mode": "manual" if force else "automatic",
                "started_at": utc_now().isoformat(),
                "total": len(collectors),
                "completed": 0,
                "current": None,
                "fetched": 0,
                "created": 0,
                "updated": 0,
                "results": [],
            }
            try:
                for collector in collectors:
                    self.progress["current"] = collector.label
                    result = await self.collect(collector, force=force)
                    result["label"] = collector.label
                    self.progress["results"].append(result)
                    self.progress["completed"] += 1
                    for key in ("fetched", "created", "updated"):
                        self.progress[key] += result.get(key, 0)
                return self.progress["results"]
            finally:
                self.progress["running"] = False
                self.progress["current"] = None
                self.progress["finished_at"] = utc_now().isoformat()

    async def collect(self, collector: Collector, *, force: bool = False) -> dict:
        now = utc_now()
        with self.sessions.begin() as db:
            # Boards share the upstream limit of their provider.
            retry_at = db.scalar(
                select(CollectionRun.retry_at)
                .where(
                    CollectionRun.retry_at > now,
                    CollectionRun.source.startswith(collector.key.split(":")[0] + ":"),
                )
                .order_by(CollectionRun.retry_at.desc())
                .limit(1)
            )
            if retry_at:
                return {
                    "source": collector.key,
                    "status": "cooldown",
                    "rate_limited": True,
                    "reason": "Délai imposé par le site",
                    "retry_at": retry_at.isoformat(),
                }
            previous = latest_run(db, collector.key)
            if (
                not force
                and previous
                and previous.status in {"ok", "partial", "running"}
                and previous.started_at
                > now
                - timedelta(
                    minutes=max(
                        self.settings.collect_minutes - 1,
                        getattr(collector, "min_interval_minutes", 0),
                    )
                )
            ):
                return {
                    "source": collector.key,
                    "status": "cooldown",
                    "reason": "Prochain créneau automatique",
                }
            run = CollectionRun(source=collector.key, started_at=now, status="running")
            db.add(run)
            db.flush()
            run_id = run.id
            previous_items = {
                listing.source_key.removeprefix("id:"): ListingInput.model_validate(
                    listing.snapshot
                )
                for listing in db.scalars(select(Listing).where(Listing.source == collector.key))
                if listing.source_key.startswith("id:") and listing.closed_at is None
            }

        try:
            batch = await collector.fetch(self.client, previous_items)
            now = utc_now()
            with self.sessions.begin() as db:
                run = db.get(CollectionRun, run_id)
                previous_listings = db.scalars(
                    select(Listing).where(Listing.source == collector.key)
                ).all()
                seen, known = set(), {listing.source_key for listing in previous_listings}
                for item in batch.listings:
                    if f"id:{item.external_id}" not in known and not is_internship(
                        item, plain_text(item.description)
                    ):
                        continue
                    listing, created, changed = ingest(db, collector.key, item, self.settings, now)
                    seen.add(listing.id)
                    run.created += int(created)
                    run.updated += int(changed)
                if batch.complete and batch.authoritative:
                    for listing in previous_listings:
                        if listing.id not in seen and listing.closed_at is None:
                            listing.misses += 1
                            if listing.misses >= 2:
                                listing.closed_at = now
                                refresh_offer(listing.offer, self.settings, now)
                run.fetched = (
                    batch.fetched
                    if batch.fetched is not None
                    else len(batch.listings) + batch.skipped
                )
                run.skipped = batch.skipped
                run.finished_at = now
                run.status = "ok" if batch.complete else "partial"
                run.error = None if batch.complete else "Instantané incomplet."
            LOG.info(
                "collection source=%s status=%s fetched=%s created=%s updated=%s",
                run.source,
                run.status,
                run.fetched,
                run.created,
                run.updated,
            )
            return {
                "source": run.source,
                "status": run.status,
                "created": run.created,
                "fetched": run.fetched,
                "updated": run.updated,
            }
        except asyncio.CancelledError:
            self.finish_error(run_id, "interrupted", "Collecte interrompue.")
            raise
        except SourceError as exc:
            self.finish_error(run_id, "failed", str(exc), exc.retry_after)
            return {
                "source": collector.key,
                "status": "failed",
                "rate_limited": bool(exc.retry_after),
            }
        except Exception as exc:
            self.finish_error(run_id, "failed", f"Erreur de collecte ({type(exc).__name__}).")
            return {"source": collector.key, "status": "failed"}

    def finish_error(
        self,
        run_id: int,
        status: str,
        error: str,
        retry_after: int | None = None,
    ) -> None:
        with self.sessions.begin() as db:
            run = db.get(CollectionRun, run_id)
            run.status, run.error, run.finished_at = status, error, utc_now()
            if retry_after:
                run.retry_at = run.finished_at + timedelta(seconds=retry_after)
        LOG.warning("collection source=%s status=%s error=%s", run.source, status, error)
