import asyncio
import fcntl
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete, update

from stageradar.collection import Collection
from stageradar.collectors.ashby import Ashby
from stageradar.collectors.base import Collector
from stageradar.collectors.bnp import BNP
from stageradar.collectors.bpce import BPCE
from stageradar.collectors.career_sites import Intrinsec, Synetis
from stageradar.collectors.dassault import Dassault
from stageradar.collectors.greenhouse import Greenhouse
from stageradar.collectors.kpmg import KPMG
from stageradar.collectors.lever import Lever
from stageradar.collectors.njoyn import CGI
from stageradar.collectors.orange_jobs import OrangeJobs
from stageradar.collectors.public_careers import PublicCareers
from stageradar.collectors.smartrecruiters import SmartRecruiters
from stageradar.collectors.successfactors import SuccessFactors
from stageradar.collectors.teamtailor import Teamtailor
from stageradar.collectors.thales import Thales
from stageradar.collectors.workday import Workday
from stageradar.collectors.yello import YelloEY
from stageradar.config import CAREER_LABELS, Settings
from stageradar.database import CollectionRun, Notification, open_database, session_factory, upgrade
from stageradar.schemas import PARIS, utc_now
from stageradar.telegram import Telegram


@contextmanager
def exclusive_instance(data_dir: Path) -> Iterator[None]:
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                "Ce répertoire est déjà utilisé par une instance StageRadar."
            ) from None
        yield


class Runtime:
    def __init__(self, settings: Settings, sessions, source_client, bot_client) -> None:
        self.settings = settings
        self.sessions = sessions
        collectors: list[Collector] = [
            *(Greenhouse(board, label) for board, label in settings.greenhouse_boards.items()),
            *(
                SmartRecruiters(company, label, nationwide=company.casefold() == "advens")
                for company, label in settings.smartrecruiters_companies.items()
            ),
        ]
        collectors.extend(
            Lever(region, board, label)
            for key, label in settings.lever_boards.items()
            for region, _, board in [key.partition(":")]
        )
        collectors.extend(Ashby(board, label) for board, label in settings.ashby_boards.items())
        collectors.extend(
            Teamtailor(board, label) for board, label in settings.teamtailor_boards.items()
        )
        collectors.extend(
            SuccessFactors(board, label) for board, label in settings.successfactors_boards.items()
        )
        collectors.extend(Workday(board, label) for board, label in settings.workday_boards.items())
        career_collectors = {
            "synetis": Synetis,
            "intrinsec": Intrinsec,
            "ey": YelloEY,
            "kpmg": KPMG,
            "orange": OrangeJobs,
            "cgi": CGI,
            "dassault": Dassault,
            "bpce": BPCE,
            "bnp": BNP,
        }
        collectors.extend(
            career_collectors[board]()
            if board in career_collectors
            else PublicCareers(board, CAREER_LABELS[board])
            for board in settings.career_sites
        )
        if settings.thales_enabled:
            collectors.append(Thales())
        self.collection = Collection(sessions, collectors, settings, source_client)
        self.telegram = Telegram(settings, sessions, bot_client, self.collection)
        self.scheduler = AsyncIOScheduler(timezone=PARIS, job_defaults={"coalesce": True})
        self.manual_task: asyncio.Task | None = None

    def start(self) -> None:
        with self.sessions.begin() as db:
            db.execute(
                update(CollectionRun)
                .where(CollectionRun.status == "running")
                .values(status="interrupted", error="Arrêt de l’instance.", finished_at=utc_now())
            )
            db.execute(
                update(Notification)
                .where(Notification.status == "sending")
                .values(status="uncertain")
            )
        if not self.settings.run_scheduler:
            return
        self.scheduler.add_job(
            self.collection.run,
            "interval",
            minutes=self.settings.collect_minutes,
            misfire_grace_time=60,
        )
        self.scheduler.add_job(self.maintenance, "cron", hour=3, minute=25)
        if self.settings.collect_on_start:
            self.scheduler.add_job(self.collection.run, misfire_grace_time=60)
        if self.settings.telegram_enabled:
            self.scheduler.add_job(self.telegram.deliver, "interval", seconds=15)
            if self.settings.telegram_digest:
                self.scheduler.add_job(self.telegram.enqueue_digest, "cron", hour=8, minute=0)
                self.telegram.enqueue_digest()
            if self.settings.telegram_commands:
                self.scheduler.add_job(self.telegram.poll, "interval", seconds=15)
        self.scheduler.start()

    def trigger(self, sources: list[str] | None = None) -> bool:
        if (self.manual_task and not self.manual_task.done()) or self.collection.lock.locked():
            return False
        self.manual_task = asyncio.create_task(self.collection.run(force=True, sources=sources))
        return True

    async def close(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            # AsyncIOScheduler schedules shutdown on the event loop.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        if self.manual_task:
            self.manual_task.cancel()
            await asyncio.gather(self.manual_task, return_exceptions=True)

    async def maintenance(self) -> None:
        now = utc_now()
        with self.sessions.begin() as db:
            db.execute(
                delete(CollectionRun).where(
                    CollectionRun.finished_at < now - timedelta(days=90),
                    (CollectionRun.retry_at.is_(None) | (CollectionRun.retry_at <= now)),
                )
            )
            db.execute(
                delete(Notification).where(
                    Notification.offer_id.is_(None),
                    Notification.next_attempt < now - timedelta(days=14),
                    Notification.status.not_in(["pending", "sending"]),
                )
            )


@asynccontextmanager
async def running(settings: Settings) -> AsyncIterator[Runtime]:
    with exclusive_instance(settings.data_dir):
        engine = open_database(settings.data_dir)
        try:
            upgrade(engine)
            async with (
                httpx.AsyncClient(
                    timeout=10,
                    trust_env=False,
                    follow_redirects=False,
                    headers={"User-Agent": "StageRadar/0.1 (local internship monitor)"},
                ) as source_client,
                httpx.AsyncClient(
                    timeout=15, trust_env=False, follow_redirects=False
                ) as bot_client,
            ):
                runtime = Runtime(settings, session_factory(engine), source_client, bot_client)
                runtime.start()
                try:
                    yield runtime
                finally:
                    await runtime.close()
        finally:
            engine.dispose()
