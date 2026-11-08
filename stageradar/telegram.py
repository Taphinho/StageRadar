import asyncio
import logging
from datetime import UTC, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from stageradar.collection import Collection, source_states
from stageradar.config import Settings
from stageradar.database import Notification, Offer
from stageradar.schemas import PARIS, paris_date, utc_now

LOG = logging.getLogger(__name__)
HELP = "StageRadar — /start /latest /top /stats /sources /help"


def summarize(offers: list[Offer], heading: str) -> str:
    lines = [f"{offer.score}/100 · {offer.title[:100]} · {offer.employer[:60]}" for offer in offers]
    return heading + "\n\n" + ("\n".join(lines) if lines else "Aucune offre.")


def offer_message(offer: Offer) -> str:
    details = offer.details
    duration = f"{details['duration_months']} mois" if details["duration_months"] else "Inconnue"
    explanations = [reason["detail"] for reason in offer.reasons if reason["points"] > 0]
    published = paris_date(offer.published_at).isoformat() if offer.published_at else "Inconnue"
    return (
        f"🚀 NOUVELLE OFFRE — StageRadar\n\n🏢 {offer.employer}\n💼 {offer.title}\n"
        f"📍 {details['location'] or 'Inconnue'}\n📅 Début : {details['start_date'] or 'Inconnu'}\n"
        f"⏳ Durée : {duration}\n🎯 Pertinence : {offer.score}/100\n🕒 Publiée : {published}\n"
        f"🔎 Source : {details['primary_source']}\n\nCompétences : "
        f"{', '.join(details['skills'])[:400] or 'Non précisées'}\n\n"
        f"Pourquoi cette offre correspond :\n{'; '.join(explanations)[:900]}"
    )


class Telegram:
    def __init__(
        self,
        settings: Settings,
        sessions: sessionmaker,
        client: httpx.AsyncClient,
        collection: Collection,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.client = client
        self.collection = collection
        self.offset: int | None = None
        self.poll_wait_until = utc_now()

    def url(self, method: str) -> str:
        token = self.settings.telegram_token.get_secret_value()
        return f"https://api.telegram.org/bot{token}/{method}"

    async def deliver(self) -> None:
        now = utc_now()
        hour = now.replace(tzinfo=UTC).astimezone(PARIS).hour
        start, end = self.settings.quiet_start, self.settings.quiet_end
        quiet = start <= hour < end if start <= end else hour >= start or hour < end
        with self.sessions() as db:
            delayed = db.scalar(
                select(Notification.key)
                .where(
                    Notification.status == "pending",
                    Notification.attempts > 0,
                    Notification.next_attempt > now,
                )
                .limit(1)
            )
        if delayed:
            return
        for _ in range(8):
            with self.sessions.begin() as db:
                candidates = select(Notification).where(
                    Notification.status == "pending", Notification.next_attempt <= now
                )
                if quiet:
                    candidates = candidates.where(Notification.offer_id.is_(None))
                note = db.scalar(
                    candidates.order_by(
                        Notification.offer_id.is_not(None).desc(), Notification.next_attempt
                    ).limit(1)
                )
                if not note:
                    return
                offer = db.get(Offer, note.offer_id) if note.offer_id else None
                if offer and (
                    offer.expired
                    or offer.hidden
                    or not offer.details["internship"]
                    or offer.score < self.settings.alert_threshold
                ):
                    note.status = "suppressed"
                    continue
                payload: dict = {
                    "chat_id": self.settings.telegram_chat_id,
                    "text": (offer_message(offer) if offer else note.body)[:4000],
                    "link_preview_options": {"is_disabled": True},
                }
                if offer:
                    payload["reply_markup"] = {
                        "inline_keyboard": [
                            [{"text": "Ouvrir l’annonce", "url": offer.details["apply_url"]}]
                        ]
                    }
                note.status = "sending"
                note.attempts += 1
            status, delay = await self.send(payload, note.attempts)
            with self.sessions.begin() as db:
                current = db.get(Notification, note.key)
                current.status = status
                if status == "sent":
                    current.delivered_at = utc_now()
                if delay:
                    current.next_attempt = utc_now() + timedelta(seconds=delay)
            if status != "sent":
                LOG.warning("telegram delivery status=%s attempt=%s", status, note.attempts)
            if delay:
                return
            await asyncio.sleep(1.1)

    async def send(self, payload: dict, attempts: int) -> tuple[str, int | None]:
        try:
            response = await self.client.post(self.url("sendMessage"), json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return (
                ("pending", min(3600, 30 * 2 ** min(attempts, 7)))
                if attempts < 8
                else ("failed", None)
            )
        except httpx.HTTPError:
            return "uncertain", None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if response.status_code == 429 or body.get("error_code") == 429:
            parameters = body.get("parameters")
            delay = parameters.get("retry_after", 60) if isinstance(parameters, dict) else 60
            return "pending", max(1, min(delay, 86400)) if type(delay) is int else 60
        if response.is_success and body.get("ok") is True:
            return "sent", None
        if 400 <= response.status_code < 500:
            return "failed", None
        return "uncertain", None

    def enqueue_digest(self) -> None:
        now = utc_now()
        local = now.replace(tzinfo=UTC).astimezone(PARIS)
        if local.hour < 8:
            return
        since = (
            (local - timedelta(days=1))
            .replace(hour=8, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        until = (
            local.replace(hour=8, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
        key = f"digest:{local.date()}"
        with self.sessions.begin() as db:
            if db.get(Notification, key):
                return
            offers = db.scalars(
                select(Offer)
                .where(
                    Offer.first_seen >= since,
                    Offer.first_seen < until,
                    Offer.score >= self.settings.alert_threshold,
                    ~Offer.hidden,
                    ~Offer.expired,
                )
                .order_by(Offer.score.desc(), Offer.first_seen.desc())
                .limit(8)
            ).all()
            due = db.scalar(
                select(func.count(Offer.id)).where(
                    Offer.reminder_on <= local.date(),
                    Offer.status.not_in(["archived", "rejected", "offer"]),
                )
            )
            text = summarize(offers, "☀️ StageRadar · Résumé quotidien")
            db.add(Notification(key=key, body=f"{text}\n\nRappels à traiter : {due}"))

    async def poll(self) -> None:
        if utc_now() < self.poll_wait_until:
            return
        try:
            response = await self.client.post(
                self.url("getUpdates"),
                json={"offset": self.offset, "timeout": 10, "allowed_updates": ["message"]},
            )
            if response.status_code == 429:
                self.poll_wait_until = utc_now() + timedelta(seconds=60)
            response.raise_for_status()
            data = response.json()
            if data.get("ok") is not True or not isinstance(data.get("result"), list):
                return
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            LOG.warning("telegram polling error=%s", type(exc).__name__)
            return
        for update in data["result"]:
            if not isinstance(update, dict) or type(update.get("update_id")) is not int:
                continue
            update_id = update["update_id"]
            message = update.get("message")
            message = message if isinstance(message, dict) else {}
            chat, text = message.get("chat"), message.get("text")
            chat = chat if isinstance(chat, dict) else {}
            text = text if isinstance(text, str) else ""
            command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text.strip() else ""
            if chat.get("id") == self.settings.telegram_chat_id and command.startswith("/"):
                with self.sessions.begin() as db:
                    key = f"command:{update_id}"
                    if db.get(Notification, key) is None:
                        db.add(Notification(key=key, body=self.reply(db, command)))
            self.offset = update_id + 1

    def reply(self, db: Session, command: str) -> str:
        if command in {"/latest", "/top"}:
            ordering = Offer.first_seen.desc() if command == "/latest" else Offer.score.desc()
            offers = db.scalars(
                select(Offer)
                .where(~Offer.expired, ~Offer.hidden)
                .order_by(ordering, Offer.id.desc())
                .limit(5)
            ).all()
            return summarize(
                offers,
                "📡 StageRadar · Dernières offres"
                if command == "/latest"
                else "🎯 StageRadar · Meilleures offres",
            )
        if command == "/stats":
            return f"StageRadar · {db.scalar(select(func.count(Offer.id)))} offres détectées."
        if command == "/sources":
            states = source_states(db, self.collection.collectors, self.settings)
            return "Sources automatiques\n" + (
                "\n".join(
                    f"{state['label']} : {state['last_status']}"
                    for state in states
                    if state["mode"] == "automatic"
                )
                or "Aucune source configurée."
            )
        return HELP
