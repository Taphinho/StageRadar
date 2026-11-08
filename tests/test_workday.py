import asyncio
import json
from datetime import datetime

import httpx
import pytest

from stageradar.collectors import workday
from stageradar.collectors.base import SourceError
from stageradar.collectors.workday import FRANCE, Workday


def test_public_workday_paginates_deduplicates_and_uses_posting_date(monkeypatch):
    monkeypatch.setattr(workday, "PAGE_SIZE", 1)

    async def skip_wait(_delay):
        pass

    monkeypatch.setattr(workday.asyncio, "sleep", skip_wait)
    seen = []
    path = "/job/Paris/Stage-Cyber_REQ1"

    def respond(request):
        assert request.url.host == "cc.wd3.myworkdayjobs.com"
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /refreshFacet/")
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["appliedFacets"] == {"locationCountry": [FRANCE]}
            seen.append((body["searchText"], body["offset"]))
            if body["offset"] == 0:
                row = {"title": "Stage Cyber", "externalPath": path, "locationsText": "Paris"}
            else:
                row = {"title": "Stage abroad", "externalPath": "/job/London/Stage_REQ2"}
            return httpx.Response(
                200, json={"total": 2 if body["offset"] == 0 else 0, "jobPostings": [row]}
            )
        if request.url.path.endswith("Stage_REQ2"):
            return httpx.Response(
                200, json={"jobPostingInfo": {"country": {"descriptor": "United Kingdom"}}}
            )
        assert request.url.path.endswith(path)
        return httpx.Response(
            200,
            json={
                "jobPostingInfo": {
                    "country": {"id": FRANCE},
                    "posted": True,
                    "canApply": True,
                    "jobReqId": "REQ1",
                    "title": "Stage Cyber",
                    "location": "Paris",
                    "jobDescription": "<p>Stage de 6 mois, début avril 2027.</p>",
                    "startDate": "2026-11-06",
                    "externalUrl": "https://attacker.example/job",
                }
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await Workday("chanel", "Chanel").fetch(client, {})

    batch = asyncio.run(run())
    assert batch.complete and not batch.authoritative
    assert len(batch.listings) == 1
    item = batch.listings[0]
    assert item.published_at == datetime(2026, 11, 6)
    assert item.start_date is None
    assert str(item.original_url) == "https://cc.wd3.myworkdayjobs.com/ChanelCareers" + path
    assert seen == [("stage", 0), ("stage", 1), ("intern", 0), ("intern", 1)]


def test_workday_rejects_invalid_payload_and_untrusted_job_paths(monkeypatch):
    async def skip_wait(_delay):
        pass

    monkeypatch.setattr(workday.asyncio, "sleep", skip_wait)
    mode = "paths"

    def respond(request):
        assert request.url.host == "ag.wd3.myworkdayjobs.com"
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if mode == "bad":
            return httpx.Response(200, json={"error": "failed"})
        return httpx.Response(
            200,
            json={
                "total": 2,
                "jobPostings": [
                    {"title": "Stage", "externalPath": "https://attacker.example/job"},
                    {"title": "Stage", "externalPath": "/job/%2e%2e/private"},
                ],
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await Workday("airbus", "Airbus").fetch(client, {})

    batch = asyncio.run(run())
    assert not batch.complete
    assert not batch.listings
    mode = "bad"
    with pytest.raises(SourceError, match="pagination"):
        asyncio.run(run())


def test_workday_rate_limit_is_preserved(monkeypatch):
    async def skip_wait(_delay):
        pass

    monkeypatch.setattr(workday.asyncio, "sleep", skip_wait)

    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(429, headers={"Retry-After": "123"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await Workday("chanel", "Chanel").fetch(client, {})

    with pytest.raises(SourceError) as exc:
        asyncio.run(run())
    assert exc.value.retry_after == 123
