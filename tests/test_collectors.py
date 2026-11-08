import asyncio
from datetime import timedelta

import httpx
from sqlalchemy import select, update

from stageradar.collection import Collection
from stageradar.collectors.greenhouse import Greenhouse
from stageradar.collectors.smartrecruiters import SmartRecruiters
from stageradar.database import CollectionRun, Offer, open_database, session_factory, upgrade
from stageradar.schemas import utc_now


def greenhouse_job(example):
    return {
        "id": 45,
        "title": example.title,
        "content": "&lt;p&gt;" + example.description + "&lt;/p&gt;",
        "absolute_url": str(example.original_url),
        "location": {"name": example.location},
        "first_published": example.published_at.isoformat(),
        "updated_at": "2026-11-05T10:00:00Z",
    }


def test_snapshot_expiration_requires_two_successes(settings, example):
    row = greenhouse_job(example)
    states = [
        {"jobs": [row]},
        {"jobs": []},
        {"jobs": [{}]},
        {"jobs": []},
        {"jobs": [row]},
    ]

    def handle(request):
        assert request.url.host == "boards-api.greenhouse.io"
        assert request.url.params["content"] == "true"
        return httpx.Response(200, json=states.pop(0))

    async def scenario():
        engine = open_database(settings.data_dir)
        upgrade(engine)
        sessions = session_factory(engine)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            source = Greenhouse("synthetic", "Thales")
            collection = Collection(sessions, [source], settings, client)
            for step, expired in enumerate([False, False, False, True, False]):
                result = (await collection.run())[0]
                if step == 2:
                    assert result["status"] == "failed"
                with sessions.begin() as db:
                    offer = db.scalars(select(Offer)).one()
                    assert offer.expired is expired
                    assert offer.listings[0].snapshot["description"] == row["content"]
                    assert offer.published_at == example.published_at
                    db.execute(
                        update(CollectionRun).values(started_at=utc_now() - timedelta(hours=1))
                    )
        engine.dispose()

    asyncio.run(scenario())


def test_provider_rate_limit_does_not_stop_other_providers(settings):
    hosts = []

    def handle(request):
        hosts.append(request.url.host)
        if request.url.host == "boards-api.greenhouse.io":
            return httpx.Response(429, headers={"Retry-After": "3600"})
        return httpx.Response(200, json={"content": [], "totalFound": 0})

    async def scenario():
        engine = open_database(settings.data_dir)
        upgrade(engine)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            collection = Collection(
                session_factory(engine),
                [
                    Greenhouse("a", "A"),
                    Greenhouse("b", "B"),
                    SmartRecruiters("c", "C"),
                ],
                settings,
                client,
            )
            result = await collection.run()
            assert [row["status"] for row in result] == ["failed", "cooldown", "ok"]
            assert hosts == ["boards-api.greenhouse.io", "api.smartrecruiters.com"]
        engine.dispose()

    asyncio.run(scenario())


def test_smartrecruiters_reads_validated_id_and_reuses_details(settings, example):
    requests = []
    summary = {
        "id": "123",
        "name": example.title,
        "releasedDate": "2026-11-05T13:00:00.000Z",
        "location": {"region": "IDF", "city": "Palaiseau"},
        "typeOfEmployment": {"id": "permanent"},
        "ref": "http://169.254.169.254/metadata",
    }
    detail = summary | {
        "postingUrl": "https://example.com/jobs/123",
        "applyUrl": "https://example.com/apply/123",
        "jobAd": {
            "sections": {
                "jobDescription": {"title": "Missions", "text": example.description},
                "additionalInformation": "Informations supplémentaires",
            }
        },
    }

    def handle(request):
        assert request.url.host == "api.smartrecruiters.com"
        requests.append(request.url.path)
        if request.url.path.endswith("/123"):
            return httpx.Response(200, json=detail)
        return httpx.Response(200, json={"content": [summary], "totalFound": 1})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            collector = SmartRecruiters("example", example.employer)
            batch = await collector.fetch(client, {})
            assert batch.complete
            assert batch.listings[0].title == example.title
            assert (
                batch.listings[0].description
                == example.description + "\nInformations supplémentaires"
            )
            cached = await collector.fetch(client, {"123": batch.listings[0]})
            assert cached.complete
            assert cached.listings == batch.listings
            old_without_details = batch.listings[0].model_copy(update={"description": ""})
            recovered = await collector.fetch(client, {"123": old_without_details})
            assert recovered.listings == batch.listings
        assert requests == [
            "/v1/companies/example/postings",
            "/v1/companies/example/postings/123",
            "/v1/companies/example/postings",
            "/v1/companies/example/postings",
            "/v1/companies/example/postings/123",
        ]

    asyncio.run(scenario())


def test_smartrecruiters_nationwide_keeps_lille_and_prioritizes_idf(monkeypatch, example):
    from stageradar.collectors import smartrecruiters

    monkeypatch.setattr(smartrecruiters, "MAX_DETAILS", 1)
    rows = [
        {
            "id": "123",
            "name": "Stage Audit et Pentest",
            "location": {"region": "Hauts-de-France", "city": "Lille"},
            "releasedDate": "2026-11-05T13:00:00.000Z",
        },
        {
            "id": "456",
            "name": example.title,
            "location": {"region": "IDF", "city": "Palaiseau"},
            "releasedDate": "2026-11-05T13:00:00.000Z",
        },
    ]

    def handle(request):
        for row in rows:
            if request.url.path.endswith("/" + row["id"]):
                return httpx.Response(
                    200,
                    json=row
                    | {
                        "postingUrl": "https://example.org/jobs/" + row["id"],
                        "jobAd": {"sections": {"jobDescription": example.description}},
                    },
                )
        return httpx.Response(200, json={"content": rows, "totalFound": 2})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            collector = SmartRecruiters("ADVENS", "Advens", nationwide=True)
            first = await collector.fetch(client, {})
            assert [item.external_id for item in first.listings] == ["456"]
            second = await collector.fetch(client, {"456": first.listings[0]})
            assert second.complete
            assert [item.location for item in second.listings] == ["Palaiseau", "Lille"]

    asyncio.run(scenario())
