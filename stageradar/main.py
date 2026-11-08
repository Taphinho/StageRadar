import base64
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, time, timedelta
from html import unescape
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import selectinload
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import HTMLResponse, JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from stageradar.collection import source_states
from stageradar.config import CAREER_NOTES, PRIORITY_CAREER_LINKS, Settings
from stageradar.database import ROOT, CollectionRun, Listing, Notification, Offer, Revision
from stageradar.offers import ingest
from stageradar.resume import analyze
from stageradar.resume_import import extract_resume
from stageradar.runtime import running
from stageradar.schemas import (
    MANUAL_SOURCES,
    PARIS,
    ApplicationPatch,
    ListingInput,
    ManualInput,
    ResumeFileInput,
    ResumeInput,
    Status,
    paris_date,
    utc_now,
)
from stageradar.scoring import DOMAINS, category, normalize

WEB_DIR = ROOT / "stageradar" / "web"

for logger in ("httpx", "httpcore"):
    # HTTP client URLs can contain the Telegram token.
    logging.getLogger(logger).setLevel(logging.CRITICAL)


class WebProtection:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        password = settings.web_password.get_secret_value() if settings.web_password else ""
        self.credentials = (
            base64.b64encode(f"{settings.web_username}:{password}".encode()) if password else b""
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        path = scope["path"]

        async def secured_send(message):
            if message["type"] == "http.response.start":
                outgoing = MutableHeaders(scope=message)
                outgoing["X-Content-Type-Options"] = "nosniff"
                outgoing["Referrer-Policy"] = "no-referrer"
                outgoing["X-Frame-Options"] = "DENY"
                if path not in {"/docs", "/redoc"}:
                    outgoing["Content-Security-Policy"] = (
                        "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
                    )
                if path.startswith("/api/"):
                    outgoing["Cache-Control"] = "no-store"
                elif path in {"/", "/index.html", "/suggestions", "/app.js", "/styles.css"}:
                    outgoing["Cache-Control"] = "no-cache"
            await send(message)

        if self.credentials and path != "/health":
            scheme, _, provided = headers.get("authorization", "").partition(" ")
            if scheme.lower() != "basic" or not secrets.compare_digest(
                provided.encode(), self.credentials
            ):
                response = JSONResponse(
                    {"detail": "Authentification requise."},
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="StageRadar"'},
                )
                await response(scope, receive, secured_send)
                return
        if scope["method"] not in {"POST", "PATCH", "PUT", "DELETE"}:
            await self.app(scope, receive, secured_send)
            return

        origin = headers.get("origin")
        if origin and not self.same_host(origin, headers.get("host")):
            response = JSONResponse({"detail": "Origine refusée."}, status_code=403)
            await response(scope, receive, secured_send)
            return
        if headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            response = JSONResponse({"detail": "Corps JSON requis."}, status_code=415)
            await response(scope, receive, secured_send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            limit = 6_800_000 if path == "/api/resume/import" else 1_250_000
            if len(body) + len(chunk) > limit:
                response = JSONResponse({"detail": "Requête trop volumineuse."}, status_code=413)
                await response(scope, receive, secured_send)
                return
            body.extend(chunk)
            if not message.get("more_body"):
                break
        ready = True

        async def replay():
            nonlocal ready
            if ready:
                ready = False
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, secured_send)

    @staticmethod
    def same_host(origin: str, host: str | None) -> bool:
        try:
            parsed = urlsplit(origin)
            return parsed.scheme in {"http", "https"} and parsed.netloc == host
        except ValueError:
            return False


def iso(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def present(offer: Offer, full: bool = False) -> dict:
    details = {key: value for key, value in offer.details.items() if key != "description" or full}
    return {
        "id": offer.id,
        "employer": offer.employer,
        "title": unescape(offer.title),
        "first_seen": iso(offer.first_seen),
        "last_seen": iso(offer.last_seen),
        "published_at": iso(offer.published_at),
        "expired": offer.expired,
        "score": offer.score,
        "category": category(offer.score),
        "reasons": [
            reason | {"detail": paris_date(offer.published_at).isoformat()}
            if reason["criterion"] == "freshness" and offer.published_at
            else reason
            for reason in offer.reasons
        ],
        "domains": offer.domains,
        "status": offer.status,
        "favorite": offer.favorite,
        "hidden": offer.hidden,
        "applied_on": offer.applied_on,
        "reminder_on": offer.reminder_on,
        **details,
        **(
            {
                "notes": offer.notes,
                "sources": [
                    {
                        "id": listing.id,
                        "source": listing.source,
                        "first_seen": iso(listing.first_seen),
                        "last_seen": iso(listing.last_seen),
                        "closed_at": iso(listing.closed_at),
                        "published_at": iso(datetime.fromisoformat(published))
                        if (published := listing.snapshot.get("published_at"))
                        else None,
                        "snapshot": listing.snapshot,
                    }
                    for listing in sorted(offer.listings, key=lambda row: row.id)
                ],
            }
            if full
            else {}
        ),
    }


def create_app(config: Settings | None = None) -> FastAPI:
    settings = config or Settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with running(settings) as runtime:
            app.state.runtime = runtime
            yield

    app = FastAPI(title="StageRadar", version="0.1.0", lifespan=lifespan)
    app.add_middleware(WebProtection, settings=settings)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts, www_redirect=False
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, error: RequestValidationError):
        return JSONResponse(
            {
                "detail": [
                    {key: issue[key] for key in ("loc", "msg", "type")} for issue in error.errors()
                ]
            },
            status_code=422,
        )

    @app.post("/api/resume/analyze", tags=["Candidatures"])
    async def resume(request: Request, profile: ResumeInput) -> dict:
        with request.app.state.runtime.sessions() as db:
            return analyze(db, profile.text)

    @app.get("/health", tags=["Système"])
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/offers", tags=["Offres"])
    async def offers(
        request: Request,
        q: Annotated[str, Query(max_length=200)] = "",
        company: Annotated[str, Query(max_length=250)] = "",
        location: Annotated[str, Query(max_length=200)] = "",
        source: Annotated[str, Query(max_length=100)] = "",
        domain: Annotated[str, Query(max_length=50)] = "",
        min_score: Annotated[int, Query(ge=0, le=100)] = 0,
        days: Annotated[int | None, Query(ge=1, le=365)] = None,
        published_days: Annotated[int | None, Query(ge=1, le=365)] = None,
        state: Status | None = None,
        favorite: bool = False,
        hidden: bool = False,
        excluded_only: bool = False,
        expired: bool = False,
        sort: Literal["score", "date", "published"] = "score",
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 30,
    ) -> dict:
        stmt = select(Offer).where(Offer.score >= min_score)
        for word in normalize(q).split():
            stmt = stmt.where(Offer.search_text.contains(word, autoescape=True))
        if company:
            stmt = stmt.where(Offer.employer_key.contains(normalize(company), autoescape=True))
        if location:
            stmt = stmt.where(
                func.normalize_text(Offer.details["location"].as_string()).contains(
                    normalize(location), autoescape=True
                )
            )
        if source:
            stmt = stmt.where(Offer.listings.any(Listing.source == source))
        if domain:
            if domain not in DOMAINS:
                raise HTTPException(422, "Domaine inconnu.")
            values = func.json_each(Offer.domains).table_valued("value")
            stmt = stmt.where(
                select(1).select_from(values).where(values.c.value == domain).exists()
            )
        if days:
            stmt = stmt.where(
                func.coalesce(Offer.published_at, Offer.first_seen)
                >= utc_now() - timedelta(days=days)
            )
        if published_days:
            today = datetime.now(PARIS).date()
            first_day = today - timedelta(days=published_days - 1)
            tomorrow = today + timedelta(days=1)
            since = datetime.combine(first_day, time.min, PARIS).astimezone(UTC)
            until = datetime.combine(tomorrow, time.min, PARIS).astimezone(UTC)
            stmt = stmt.where(
                Offer.published_at >= since.replace(tzinfo=None),
                Offer.published_at < until.replace(tzinfo=None),
            )
        if state:
            stmt = stmt.where(Offer.status == state)
        if favorite:
            stmt = stmt.where(Offer.favorite)
        if excluded_only:
            stmt = stmt.where(Offer.hidden)
        elif not hidden:
            stmt = stmt.where(~Offer.hidden)
        if not expired:
            stmt = stmt.where(~Offer.expired)
        order = []
        if sort == "score":
            order.append(Offer.score.desc())
        elif sort == "published":
            order.append(Offer.published_at.desc().nulls_last())
        with request.app.state.runtime.sessions() as db:
            total = db.scalar(select(func.count()).select_from(stmt.subquery()))
            items = db.scalars(
                stmt.order_by(*order, Offer.first_seen.desc(), Offer.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            return {"total": total, "items": [present(item) for item in items]}

    @app.post("/api/offers/exclude-thales", tags=["Offres"])
    async def exclude_thales(request: Request) -> dict:
        with request.app.state.runtime.sessions.begin() as db:
            result = db.execute(
                update(Offer)
                .where(
                    ~Offer.hidden,
                    or_(
                        Offer.employer_key == "thales",
                        Offer.employer_key.startswith("thales "),
                        Offer.listings.any(Listing.source == "thales:fr"),
                    ),
                )
                .values(hidden=True)
            )
            return {"excluded": result.rowcount}

    @app.post("/api/offers/restore-thales", tags=["Offres"])
    async def restore_thales(request: Request) -> dict:
        with request.app.state.runtime.sessions.begin() as db:
            result = db.execute(
                update(Offer)
                .where(
                    Offer.hidden,
                    or_(
                        Offer.employer_key == "thales",
                        Offer.employer_key.startswith("thales "),
                        Offer.listings.any(Listing.source == "thales:fr"),
                    ),
                )
                .values(hidden=False)
            )
            return {"restored": result.rowcount}

    @app.post("/api/offers/import", status_code=201, tags=["Offres"])
    async def import_offer(request: Request, item: ManualInput) -> dict:
        source = f"manual:{item.platform}"
        with request.app.state.runtime.sessions.begin() as db:
            normalized = ListingInput.model_validate(item.model_dump(exclude={"platform"}))
            listing, created, updated = ingest(db, source, normalized, settings, utc_now())
            return {
                "created": created,
                "updated": updated,
                "offer": present(listing.offer, full=True),
            }

    @app.get("/api/offers/{offer_id}", tags=["Offres"])
    async def offer_detail(request: Request, offer_id: int) -> dict:
        with request.app.state.runtime.sessions() as db:
            offer = db.get(Offer, offer_id)
            if not offer:
                raise HTTPException(404, "Offre introuvable.")
            return present(offer, full=True)

    @app.get("/api/offers/{offer_id}/revisions", tags=["Offres"])
    async def revisions(request: Request, offer_id: int) -> list[dict]:
        with request.app.state.runtime.sessions() as db:
            if not db.get(Offer, offer_id):
                raise HTTPException(404, "Offre introuvable.")
            rows = db.scalars(
                select(Revision)
                .join(Listing)
                .where(Listing.offer_id == offer_id)
                .order_by(Revision.id.desc())
                .limit(30)
            )
            return [
                {
                    "listing_id": row.listing_id,
                    "recorded_at": iso(row.recorded_at),
                    "snapshot": row.snapshot,
                }
                for row in rows
            ]

    @app.patch("/api/offers/{offer_id}", tags=["Candidatures"])
    async def application(request: Request, offer_id: int, patch: ApplicationPatch) -> dict:
        with request.app.state.runtime.sessions.begin() as db:
            offer = db.get(Offer, offer_id, options=[selectinload(Offer.listings)])
            if not offer:
                raise HTTPException(404, "Offre introuvable.")
            for key, value in patch.model_dump(exclude_unset=True).items():
                setattr(offer, key, value)
            return present(offer, full=True)

    @app.get("/api/stats", tags=["Tableau de bord"])
    async def stats(request: Request) -> dict:
        local_date = datetime.now(PARIS).date()
        dates = [local_date - timedelta(days=index) for index in reversed(range(14))]
        boundaries = [
            datetime.combine(day, time.min, PARIS).astimezone(UTC).replace(tzinfo=None)
            for day in [*dates, local_date + timedelta(days=1)]
        ]
        with request.app.state.runtime.sessions() as db:

            def count(*conditions) -> int:
                return db.scalar(select(func.count(Offer.id)).where(*conditions))

            trend = [
                {"date": day, "count": count(Offer.first_seen >= start, Offer.first_seen < end)}
                for day, start, end in zip(dates, boundaries[:-1], boundaries[1:], strict=True)
            ]
            return {
                "total": count(),
                "today": trend[-1]["count"],
                "high": count(Offer.score >= 85, ~Offer.expired, ~Offer.hidden),
                "sent": count(
                    Offer.applied_on.is_not(None)
                    | Offer.status.in_(
                        [
                            Status.SENT,
                            Status.FOLLOW_UP,
                            Status.INTERVIEW,
                            Status.REJECTED,
                            Status.OFFER,
                        ]
                    )
                ),
                "interviews": count(Offer.status.in_([Status.INTERVIEW, Status.OFFER])),
                "reminders": count(
                    Offer.reminder_on <= local_date,
                    Offer.status.not_in([Status.ARCHIVED, Status.REJECTED, Status.OFFER]),
                ),
                "trend": trend,
            }

    @app.post("/api/resume/import", tags=["CV"])
    def import_resume(profile: ResumeFileInput) -> dict:
        try:
            return {"text": extract_resume(profile.filename, profile.content)}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/api/sources", tags=["Sources"])
    async def sources(request: Request) -> list[dict]:
        runtime = request.app.state.runtime
        with runtime.sessions() as db:
            return source_states(db, runtime.collection.collectors, settings)

    @app.get("/api/collection-progress", tags=["Sources"])
    async def collection_progress(request: Request) -> dict:
        return request.app.state.runtime.collection.progress

    @app.get("/api/runs", tags=["Sources"])
    async def runs(request: Request) -> list[dict]:
        with request.app.state.runtime.sessions() as db:
            rows = db.scalars(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(50))
            return [
                {
                    "source": row.source,
                    "status": row.status,
                    "started_at": iso(row.started_at),
                    "finished_at": iso(row.finished_at),
                    "retry_at": iso(row.retry_at),
                    "fetched": row.fetched,
                    "created": row.created,
                    "updated": row.updated,
                    "skipped": row.skipped,
                    "error": row.error,
                }
                for row in rows
            ]

    @app.post("/api/collect", status_code=status.HTTP_202_ACCEPTED, tags=["Sources"])
    async def collect(request: Request) -> dict:
        body = await request.json()
        selected = body.get("sources") if isinstance(body, dict) else None
        known = {item.key for item in request.app.state.runtime.collection.collectors}
        if selected is not None and (
            not isinstance(selected, list)
            or not selected
            or any(not isinstance(key, str) or key not in known for key in selected)
        ):
            raise HTTPException(422, "Liste de sources non valide.")
        if not request.app.state.runtime.trigger(sources=selected):
            raise HTTPException(409, "Une collecte est déjà en cours.")
        return {"status": "scheduled"}

    @app.get("/api/settings", tags=["Système"])
    async def configuration(request: Request) -> dict:
        with request.app.state.runtime.sessions() as db:
            delivery = dict(
                db.execute(
                    select(Notification.status, func.count()).group_by(Notification.status)
                ).all()
            )
        return {
            **settings.model_dump(
                mode="json",
                include={
                    "target_start",
                    "target_months",
                    "semantic_enabled",
                    "collect_minutes",
                    "keywords",
                    "locations",
                    "priority_domains",
                    "priority_employers",
                    "weights",
                    "alert_threshold",
                    "quiet_start",
                    "quiet_end",
                    "telegram_digest",
                    "telegram_commands",
                },
            ),
            "telegram_enabled": settings.telegram_enabled,
            "notifications": delivery,
            "domains": {key: values[0] for key, values in DOMAINS.items()},
            "manual_sources": MANUAL_SOURCES,
            "career_notes": CAREER_NOTES,
            "priority_career_links": {
                employer: PRIORITY_CAREER_LINKS[employer]
                for employer in settings.priority_employers
                if employer in PRIORITY_CAREER_LINKS
            },
        }

    web_shell = (WEB_DIR / "index.html").read_bytes()

    @app.api_route("/suggestions", methods=["GET", "HEAD"], include_in_schema=False)
    async def suggestions_page() -> HTMLResponse:
        return HTMLResponse(web_shell)

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
