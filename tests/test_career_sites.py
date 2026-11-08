import asyncio
from datetime import datetime

import httpx
import pytest

from stageradar.collectors.base import SourceError
from stageradar.collectors.career_sites import Intrinsec, Synetis


def test_synetis_embed_retains_stage_contract_date_and_profile():
    def respond(request):
        assert request.url.host == "www.welcomekit.co"
        assert request.url.params["organization_reference"] == "4lMLezr"
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "reference": "TEST_1",
                        "slug": "stage-iam-paris",
                        "name": "Consultant IAM",
                        "contract_type": {"fr": "Stage"},
                        "description": "<p>Missions IAM</p>",
                        "profile": "<p>Python et Linux</p>",
                        "published_at": "2026-11-05T10:00:00+01:00",
                        "offices": [
                            {"city": "Paris", "zip_code": "75008", "country": {"fr": "France"}}
                        ],
                    }
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await Synetis().fetch(client, {})

    batch = asyncio.run(run())
    assert batch.complete and batch.fetched == 1
    listing = batch.listings[0]
    assert listing.contract == "Stage"
    assert listing.published_at == datetime(2026, 11, 5, 9)
    assert "Python" in listing.description
    assert listing.location == "Paris, 75008, France"


def test_intrinsec_uses_public_nonce_without_following_widget_urls():
    def respond(request):
        assert request.url.host == "www.intrinsec.com"
        if request.url.path == "/rejoindre-intrinsec/":
            return httpx.Response(
                200,
                text='var wp_boondmanager_globals = {"nonce":"abc123","ajax_url":"https://evil.test/"};',
            )
        assert request.url.path == "/wp-admin/admin-ajax.php"
        assert request.url.params["action"] == "get-opportunities"
        assert request.url.params["_ajax_nonce"] == "abc123"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 123,
                    "state": "published",
                    "title": "Stage Analyste CERT",
                    "description": "<p>SOC</p>",
                    "criteria": "<p>SIEM et Python</p>",
                    "place": "Île-de-France",
                    "contract": "Stage",
                    "datePosted": "2026-11-05",
                },
                {"id": 124, "state": "draft"},
            ],
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await Intrinsec().fetch(client, {})

    batch = asyncio.run(run())
    assert batch.complete and batch.fetched == 2 and len(batch.listings) == 1
    assert batch.listings[0].published_at == datetime(2026, 11, 5)
    assert "SIEM" in batch.listings[0].description


def test_intrinsec_invalid_widget_is_a_source_failure():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text="<html>Maintenance</html>")
            )
        ) as client:
            return await Intrinsec().fetch(client, {})

    with pytest.raises(SourceError, match="Widget public"):
        asyncio.run(run())
