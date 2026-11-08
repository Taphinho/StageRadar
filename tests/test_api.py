import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from stageradar.config import Settings
from stageradar.main import create_app
from stageradar.schemas import PARIS

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@asynccontextmanager
async def api_client(settings, base_url="http://localhost"):
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url) as client,
    ):
        yield client


def payload(example, **extra):
    return example.model_dump(mode="json") | {"platform": "email"} | extra


async def test_suggestions_has_a_direct_page(settings):
    async with api_client(settings) as client:
        response = await client.get("/suggestions")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-cache"
        assert 'id="suggestions"' in response.text


async def test_excluded_offer_stays_excluded_after_collection_and_can_be_restored(
    settings, example
):
    async with api_client(settings) as client:
        imported = (await client.post("/api/offers/import", json=payload(example))).json()
        offer_id = imported["offer"]["id"]
        assert (
            await client.patch(f"/api/offers/{offer_id}", json={"hidden": True})
        ).status_code == 200
        assert (await client.get("/api/offers")).json()["total"] == 0
        excluded = (await client.get("/api/offers?excluded_only=true")).json()
        assert [offer["id"] for offer in excluded["items"]] == [offer_id]
        repeated = (await client.post("/api/offers/import", json=payload(example))).json()
        assert repeated["offer"]["hidden"]
        assert (await client.get("/api/offers")).json()["total"] == 0

    async with api_client(settings) as client:
        assert (await client.get("/api/offers?excluded_only=true")).json()["total"] == 1
        assert (
            await client.patch(f"/api/offers/{offer_id}", json={"hidden": False})
        ).status_code == 200
        assert (await client.get("/api/offers?excluded_only=true")).json()["total"] == 0
        assert (await client.get("/api/offers")).json()["total"] == 1


async def test_bulk_exclusion_covers_thales_only_and_is_idempotent(settings, example):
    async with api_client(settings) as client:
        for i, employer in enumerate(("Thales", "Thales Alenia Space", "Axians", "Other Thales")):
            response = await client.post(
                "/api/offers/import",
                json=payload(example, employer=employer, original_url=f"https://example.org/{i}"),
            )
            assert response.status_code == 201
        response = await client.post("/api/offers/exclude-thales", json={})
        assert response.status_code == 200
        assert response.json() == {"excluded": 2}
        visible = (await client.get("/api/offers")).json()
        assert {offer["employer"] for offer in visible["items"]} == {"Axians", "Other Thales"}
        assert (await client.get("/api/offers?excluded_only=true")).json()["total"] == 2
        assert (await client.post("/api/offers/exclude-thales", json={})).json() == {"excluded": 0}
        other = next(item for item in visible["items"] if item["employer"] == "Axians")
        await client.patch(f"/api/offers/{other['id']}", json={"hidden": True})
        assert (await client.post("/api/offers/restore-thales", json={})).json() == {"restored": 2}
        assert (await client.post("/api/offers/restore-thales", json={})).json() == {"restored": 0}
        excluded = (await client.get("/api/offers?excluded_only=true")).json()
        assert [item["employer"] for item in excluded["items"]] == ["Axians"]


async def test_publication_order_and_filter_use_source_dates(settings, example):
    today = datetime.now(PARIS).date()
    async with api_client(settings) as client:
        ids = {}
        for key, publication in (
            ("recent", today.isoformat()),
            ("boundary", (today - timedelta(days=3)).isoformat()),
            ("old", (today - timedelta(days=4)).isoformat()),
            ("future", (today + timedelta(days=1)).isoformat()),
            ("unknown", None),
        ):
            response = await client.post(
                "/api/offers/import",
                json=payload(
                    example,
                    original_url=f"https://example.org/{key}",
                    published_at=publication,
                ),
            )
            assert response.status_code == 201, response.text
            ids[key] = response.json()["offer"]["id"]

        result = (await client.get("/api/offers?sort=published")).json()
        assert [offer["id"] for offer in result["items"]] == [
            ids["future"],
            ids["recent"],
            ids["boundary"],
            ids["old"],
            ids["unknown"],
        ]
        result = (await client.get("/api/offers?sort=published&published_days=4")).json()
        assert [offer["id"] for offer in result["items"]] == [ids["recent"], ids["boundary"]]
        result = (await client.get("/api/offers?sort=date")).json()
        assert result["items"][0]["id"] == ids["unknown"]

        recent = (await client.get(f"/api/offers/{ids['recent']}")).json()
        assert recent["sources"][0]["published_at"] == recent["published_at"]
        assert recent["published_at"] == f"{today.isoformat()}T00:00:00Z"


async def test_workflow_persists_and_preserves_revision(settings, example):
    async with api_client(settings) as client:
        assert (await client.get("/health")).json() == {"status": "ok"}
        first = await client.post("/api/offers/import", json=payload(example))
        assert first.status_code == 201, first.text
        assert first.json()["created"]
        offer_id = first.json()["offer"]["id"]
        repeated = await client.post("/api/offers/import", json=payload(example))
        assert not repeated.json()["created"]
        assert not repeated.json()["updated"]
        revised = await client.post(
            "/api/offers/import",
            json=payload(
                example,
                description=example.description + "\nEntretien technique prévu.",
            ),
        )
        assert revised.json()["updated"]
        revision = (await client.get(f"/api/offers/{offer_id}/revisions")).json()
        assert revision[0]["snapshot"]["description"] == example.description
        patched = await client.patch(
            f"/api/offers/{offer_id}",
            json={
                "favorite": True,
                "status": "interview",
                "applied_on": "2026-11-05",
                "notes": "Test",
            },
        )
        assert patched.status_code == 200
        assert (await client.get("/api/offers?q=pentest&domain=offensive&favorite=true")).json()[
            "total"
        ] == 1
        assert (await client.get("/api/offers?source=manual%3Aemail")).json()["total"] == 1
        assert (await client.get("/api/offers?domain=identity")).json()["total"] == 0
        assert (await client.get("/api/stats")).json()["interviews"] == 1
        assert (
            await client.patch(f"/api/offers/{offer_id}", json={"status": None})
        ).status_code == 422

    async with api_client(settings) as client:
        assert (await client.get("/api/offers")).json()["total"] == 1
        offer = (await client.get(f"/api/offers/{offer_id}")).json()
        assert offer["status"] == "interview"
        assert offer["notes"] == "Test"
        assert offer["sources"][0]["snapshot"]["original_url"] == str(example.original_url)


async def test_cross_source_url_and_similarity_preserve_provenance(settings, example):
    async with api_client(settings) as client:
        first = (await client.post("/api/offers/import", json=payload(example))).json()
        offer_id = first["offer"]["id"]
        duplicate = (
            await client.post(
                "/api/offers/import",
                json=payload(
                    example,
                    platform="linkedin",
                    original_url="https://example.org/jobs/123?utm_medium=email",
                ),
            )
        ).json()
        assert duplicate["offer"]["id"] == offer_id
        similar = (
            await client.post(
                "/api/offers/import",
                json=payload(
                    example,
                    platform="apec",
                    original_url="https://example.net/jobs/567",
                    description=example.description + " Merci.",
                ),
            )
        ).json()
        assert similar["offer"]["id"] == offer_id
        assert {source["source"] for source in similar["offer"]["sources"]} == {
            "manual:email",
            "manual:linkedin",
            "manual:apec",
        }


@pytest.mark.parametrize(
    ("platform", "overrides"),
    [
        ("email", {"external_id": "role-2"}),
        ("indeed", {"location": "Toulouse"}),
        ("indeed", {"title": "Stage Pentest et Red Team applicative"}),
        ("indeed", {"description": "Stage en pentest."}),
        ("indeed", {"published_at": "2026-08-01T12:00:00Z"}),
        ("indeed", {"start_date": "2027-06-01", "duration_months": 4}),
    ],
)
async def test_false_duplicates_stay_distinct(settings, example, platform, overrides):
    first = payload(example, external_id="role-1", start_date="2027-04-01", duration_months=6)
    second = (
        payload(example, original_url="https://example.com/jobs/456")
        | {"platform": platform}
        | overrides
    )
    async with api_client(settings) as client:
        assert (await client.post("/api/offers/import", json=first)).json()["created"]
        assert (await client.post("/api/offers/import", json=second)).json()["created"]
        assert (await client.get("/api/offers")).json()["total"] == 2


async def test_security_controls(settings, example):
    async with api_client(settings) as client:
        assert (await client.get("/api/stats", headers={"Host": "evil.example"})).status_code == 400
        assert (
            await client.post("/api/collect", json={}, headers={"Origin": "https://evil.example"})
        ).status_code == 403
        assert (await client.post("/api/collect", data={})).status_code == 415
        bad = payload(example, original_url="javascript:alert(1)")
        assert (await client.post("/api/offers/import", json=bad)).status_code == 422
        big = {"description": "a" * 1_300_000}
        assert (await client.post("/api/offers/import", json=big)).status_code == 413
        # The importer persists URLs as links only. It performs no outgoing request.
        assert (
            await client.post(
                "/api/offers/import",
                json=payload(
                    example,
                    original_url="http://169.254.169.254/metadata",
                ),
            )
        ).status_code == 201


async def test_remote_hosts_require_credentials(settings):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, allowed_hosts=["radar.example"])
    config = settings.model_copy(
        update={
            "allowed_hosts": ["radar.example"],
            "web_password": Settings(
                _env_file=None, web_password="a-long-test-password"
            ).web_password,
        }
    )
    async with api_client(config, "https://radar.example") as client:
        assert (await client.get("/api/settings")).status_code == 401
        encoded = base64.b64encode(b"stageradar:a-long-test-password").decode()
        reply = await client.get("/api/settings", headers={"Authorization": "Basic " + encoded})
        assert reply.status_code == 200
        assert "a-long-test-password" not in reply.text
        assert "telegram_token" not in reply.text


async def test_resume_ranks_open_offers_without_persisting_text(settings, example):
    async with api_client(settings) as client:
        saved = (await client.post("/api/offers/import", json=payload(example))).json()["offer"]
        profile = "CV FICTIF DE TEST. Expérience Python et Linux."
        response = await client.post("/api/resume/analyze", json={"text": profile})
        assert response.status_code == 200
        assert profile not in response.text
        result = response.json()
        assert result["detected_skills"] == ["Python", "Linux"]
        assert result["suggestions"][0]["id"] == saved["id"]
        assert {"Burp Suite", "Docker"} <= set(result["suggestions"][0]["gaps"])
        await client.patch(f"/api/offers/{saved['id']}", json={"hidden": True})
        hidden = await client.post("/api/resume/analyze", json={"text": profile})
        assert hidden.json()["suggestions"] == []
