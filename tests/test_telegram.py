import asyncio
import json
from datetime import timedelta

import httpx
from pydantic import SecretStr
from sqlalchemy import select

from stageradar.database import Notification, open_database, session_factory, upgrade
from stageradar.offers import ingest
from stageradar.runtime import Runtime
from stageradar.schemas import utc_now


def bot_config(settings):
    return settings.model_copy(
        update={
            "telegram_token": SecretStr("12345:" + "x" * 25),
            "telegram_chat_id": 321,
            "alert_threshold": 50,
            "quiet_start": 0,
            "quiet_end": 0,
        }
    )


def test_outbox_retries_429_and_sends_once(settings, example):
    config = bot_config(settings)
    requests = []

    def handle(request):
        body = json.loads(request.content)
        assert body["chat_id"] == 321
        assert body["reply_markup"]["inline_keyboard"][0][0]["url"] == str(example.original_url)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(429, json={"parameters": {"retry_after": 60}})
        return httpx.Response(200, json={"ok": True})

    async def scenario():
        engine = open_database(config.data_dir)
        upgrade(engine)
        sessions = session_factory(engine)
        with sessions.begin() as db:
            ingest(db, "manual:email", example, config, utc_now())
            ingest(db, "manual:linkedin", example, config, utc_now())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            runtime = Runtime(config, sessions, client, client)
            runtime.start()
            await runtime.telegram.deliver()
            await runtime.telegram.deliver()
            assert len(requests) == 1
            with sessions.begin() as db:
                note = db.scalars(select(Notification)).one()
                assert note.status == "pending"
                note.next_attempt = utc_now() - timedelta(seconds=1)
            await runtime.telegram.deliver()
            await runtime.telegram.deliver()
            assert len(requests) == 2
            with sessions() as db:
                assert db.scalars(select(Notification)).one().status == "sent"
        engine.dispose()

    asyncio.run(scenario())


def test_interrupted_delivery_recovers_without_duplicate(settings):
    config = bot_config(settings)
    engine = open_database(config.data_dir)
    upgrade(engine)
    sessions = session_factory(engine)
    with sessions.begin() as db:
        db.add(Notification(key="interrupted", body="Test", status="sending"))

    async def scenario():
        async with httpx.AsyncClient() as client:
            runtime = Runtime(config, sessions, client, client)
            runtime.start()
            await runtime.telegram.deliver()

    asyncio.run(scenario())
    with sessions() as db:
        assert db.get(Notification, "interrupted").status == "uncertain"
    engine.dispose()


def test_command_requires_authorized_chat_and_is_deduplicated(settings):
    config = bot_config(settings)
    engine = open_database(config.data_dir)
    upgrade(engine)
    sessions = session_factory(engine)

    def handle(request):
        assert request.url.path.endswith("/getUpdates")
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {"update_id": 11, "message": {"chat": {"id": 120}, "text": "/top"}},
                    {"update_id": 12, "message": {"chat": {"id": 321}, "text": "/stats"}},
                ],
            },
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            runtime = Runtime(config, sessions, client, client)
            await runtime.telegram.poll()
            await runtime.telegram.poll()

    asyncio.run(scenario())
    with sessions() as db:
        note = db.scalars(select(Notification)).one()
        assert note.key == "command:12"
        assert "0 offres détectées" in note.body
    engine.dispose()


def test_rate_limit_cannot_leak_token_on_ambiguous_delivery(settings):
    config = bot_config(settings)
    engine = open_database(config.data_dir)
    upgrade(engine)
    sessions = session_factory(engine)

    def handle(request):
        raise httpx.ReadTimeout(str(request.url), request=request)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            runtime = Runtime(config, sessions, client, client)
            assert await runtime.telegram.send({"text": "Test"}, 1) == ("uncertain", None)

    asyncio.run(scenario())
    engine.dispose()
