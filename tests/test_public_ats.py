import asyncio
from datetime import datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select, update

from stageradar.collection import Collection, source_states
from stageradar.collectors import lever
from stageradar.collectors.ashby import Ashby
from stageradar.collectors.base import SourceError
from stageradar.collectors.successfactors import SuccessFactors
from stageradar.collectors.teamtailor import Teamtailor
from stageradar.config import Settings
from stageradar.database import CollectionRun, Offer, open_database, session_factory, upgrade
from stageradar.schemas import utc_now


def test_lever_paginates_eu_and_retains_qualifications(monkeypatch):
    monkeypatch.setattr(lever, "PAGE_SIZE", 2)
    offsets = []

    def respond(request):
        assert request.url.host == "api.eu.lever.co"
        skip = int(request.url.params["skip"])
        offsets.append(skip)
        return httpx.Response(
            200,
            json=[
                {
                    "id": f"test-{i}",
                    "text": "Stage SecOps",
                    "categories": {
                        "commitment": "Intern",
                        "location": "Paris",
                        "allLocations": ["Paris", "Lyon"],
                    },
                    "description": "<p>Une offre fictive.</p>",
                    "lists": [{"text": "Compétences", "content": "<li>SIEM</li>"}],
                    "hostedUrl": f"https://example.org/job/{i}",
                    "applyUrl": f"https://example.org/job/{i}/apply",
                    "workplaceType": "hybrid",
                }
                for i in range(skip, min(skip + 2, 3))
            ],
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await lever.Lever("eu", "test", "Employeur fictif").fetch(client, {})

    batch = asyncio.run(run())
    assert offsets == [0, 2]
    assert batch.complete and batch.fetched == 3
    first = batch.listings[0]
    assert "SIEM" in first.description
    assert first.location == "Paris · Lyon"
    assert first.contract == "Intern"
    assert first.remote == "hybride"
    assert first.published_at is None


def test_ashby_excludes_unlisted_postings():
    public = {
        "id": "public",
        "title": "Stage Logiciel",
        "isListed": True,
        "location": "Paris",
        "secondaryLocations": [{"location": "Lyon"}],
        "jobUrl": "https://example.org/public",
        "publishedAt": "2026-11-05T11:00:00+01:00",
    }

    async def run():
        rows = [public, public | {"id": "unlisted", "isListed": False}]
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"jobs": rows}))
        ) as client:
            return await Ashby("board.test", "Employeur fictif").fetch(client, {})

    batch = asyncio.run(run())
    assert batch.complete
    assert [item.external_id for item in batch.listings] == ["public"]
    assert batch.listings[0].published_at == datetime(2026, 11, 5, 10)
    assert batch.listings[0].location == "Paris · Lyon"


def test_teamtailor_uses_published_metadata_and_does_not_expire_by_omission():
    data = """
    <rss xmlns:tt="https://teamtailor.com/locations"><channel><item>
      <title>Stage analyste SOC</title>
      <guid>test-1</guid><link>https://example.org/jobs/1</link>
      <description><![CDATA[<p>Description fictive.</p>]]></description>
      <pubDate>Thu, 05 Nov 2026 09:55:32 +0100</pubDate><remoteStatus>hybrid</remoteStatus>
      <tt:locations><tt:location><tt:name>France</tt:name><tt:city>Paris</tt:city></tt:location></tt:locations>
    </item></channel></rss>
    """

    def respond(request):
        assert str(request.url) == "https://example.teamtailor.com/jobs.rss"
        return httpx.Response(200, content=data)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await Teamtailor("example", "Employeur fictif").fetch(client, {})

    batch = asyncio.run(run())
    assert batch.complete and not batch.authoritative
    assert batch.listings[0].published_at == datetime(2026, 11, 5, 8, 55, 32)
    assert batch.listings[0].location == "Paris"
    assert batch.listings[0].description == "<p>Description fictive.</p>"


def test_teamtailor_rejects_xml_with_entities():
    xml = '<!DOCTYPE rss [<!ENTITY fake SYSTEM "file:///tmp/fake">]><rss><channel/></rss>'

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=xml))
        ) as client:
            await Teamtailor("example", "Employeur fictif").fetch(client, {})

    with pytest.raises(SourceError, match="RSS Teamtailor non valide"):
        asyncio.run(run())


@pytest.mark.parametrize(
    "boards",
    [
        {"lever_boards": {"global:../other": "Test"}},
        {"ashby_boards": {"..": "Test"}},
        {"teamtailor_boards": {"evil.example": "Test"}},
    ],
)
def test_board_configuration_disallows_unexpected_paths_or_hosts(boards):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **boards)


def test_successfactors_french_feed_and_minimum_interval(settings):
    data = """<rss xmlns:g="http://base.google.com/ns/1.0"><channel>
    <item>
      <title>Stage DevSecOps (Paris, FR)</title>
      <link>https://example.org/jobs/123</link><guid>123</guid>
      <g:location>Paris, FR</g:location><g:expiration_date>2026-12-01</g:expiration_date>
      <description><![CDATA[<p>Description fictive.</p>]]></description>
    </item>
    <item><title>Intern</title><g:location>London, GB</g:location></item>
    </channel></rss>"""
    requests = []

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, content=data)

    async def run():
        engine = open_database(settings.data_dir)
        upgrade(engine)
        sessions = session_factory(engine)
        source = SuccessFactors("capgemini", "Capgemini")
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            collection = Collection(sessions, [source], settings, client)
            result = (await collection.run())[0]
            assert result["fetched"] == 2
            assert result["created"] == 1
            assert collection.progress["running"] is False
            assert collection.progress["completed"] == collection.progress["total"] == 1
            assert collection.progress["created"] == 1
            assert collection.progress["current"] is None
            with sessions.begin() as db:
                offer = db.scalars(select(Offer)).one()
                assert offer.title == "Stage DevSecOps"
                assert offer.published_at is None
                assert source_states(db, [source], settings)[0]["interval_minutes"] == 720
                db.execute(update(CollectionRun).values(started_at=utc_now() - timedelta(hours=11)))
            assert (await collection.run())[0]["status"] == "cooldown"
            assert (await collection.run(force=True))[0]["status"] == "ok"
        engine.dispose()

    asyncio.run(run())
    assert requests == ["https://careers.capgemini.com/sitemal.xml"] * 2


def test_successfactors_rejects_incomplete_xml():
    source = SuccessFactors("arkema", "Arkema")
    with pytest.raises(SourceError, match="RSS SuccessFactors non valide"):
        source.parse(b"<rss><channel><item></item>")


def test_thales_uses_only_public_same_origin_sitemap_links(monkeypatch):
    import json

    from stageradar.collectors.thales import ORIGIN, Thales

    async def skip_wait(_delay):
        pass

    monkeypatch.setattr("stageradar.collectors.thales.asyncio.sleep", skip_wait)
    monkeypatch.setattr(
        "stageradar.collectors.thales.utc_now",
        lambda: datetime(2026, 11, 8, tzinfo=__import__("datetime").UTC),
    )
    namespace = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    index = f"""<sitemapindex {namespace}>
    <sitemap><loc>{ORIGIN}/fr/fr/sitemap1.xml</loc></sitemap>
    <sitemap><loc>https://example.org/fr/fr/sitemap2.xml</loc></sitemap>
    </sitemapindex>"""
    listings = f"""<urlset {namespace}>
    <url><loc>{ORIGIN}/fr/fr/job/R01234/Stage-Cybersécurité</loc></url>
    <url><loc>https://example.org/fr/fr/job/R01235/Stage-Cybersécurité</loc></url>
    <url><loc>{ORIGIN}/fr/fr/job/R01236/Ingénieur-CDI</loc></url>
    </urlset>"""
    job = {
        "@type": "JobPosting",
        "identifier": {"value": "R01234"},
        "jobLocation": {"address": {"addressCountry": "France", "addressLocality": "Paris"}},
        "title": "Stage Cybersécurité",
        "description": "<p>Offre fictive.</p>",
        "datePosted": "2026-11-05",
    }
    paths = {
        "/robots.txt": "User-agent: *\nDisallow: */apply\n",
        "/fr/fr/sitemap_index.xml": index,
        "/fr/fr/sitemap1.xml": listings,
        "/fr/fr/job/R01234": f'<script type="application/ld+json">{json.dumps(job)}</script>',
    }

    def respond(request):
        assert request.url.host == "careers.thalesgroup.com"
        return httpx.Response(200, content=paths[request.url.path])

    source = Thales()

    async def run(previous=None):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await source.fetch(client, previous or {})

    batch = asyncio.run(run())
    assert batch.complete and not batch.authoritative
    assert [(item.external_id, item.location) for item in batch.listings] == [
        ("R01234", "Paris, France")
    ]
    original = batch.listings[0]
    assert original.published_at == datetime(2026, 11, 5)
    assert original.apply_url is None

    job_url = "https://thales.wd3.myworkdayjobs.com/Careers/job/Paris/Stage_R01234-1"
    workday = {
        "reqId": "R01234",
        "ats": "WORKDAY",
        "postedDate": "2026-11-04T00:00:00.000+0000",
        "applyUrl": f"{job_url}/apply",
    }
    payload = {"jobDetail": {"data": {"job": workday}}}
    paths["/fr/fr/job/R01234"] += f"<script>phApp.ddo = {json.dumps(payload)};</script>"
    refreshed = asyncio.run(run({"R01234": original}))
    assert len(refreshed.listings) == 1
    assert refreshed.listings[0].published_at == datetime(2026, 11, 4)
    assert str(refreshed.listings[0].apply_url) == job_url

    # Thales alone retains a bounded detail refresh.
    monkeypatch.setattr("stageradar.collectors.thales.DETAIL_LIMIT", 1)
    other = original.model_copy(update={"external_id": "R01237"})
    paths["/fr/fr/sitemap1.xml"] = listings.replace(
        "</urlset>",
        f"<url><loc>{ORIGIN}/fr/fr/job/R01237/Stage-Cyber</loc></url></urlset>",
    )
    paths["/fr/fr/job/R01237"] = (
        '<script type="application/ld+json">'
        + json.dumps(job | {"identifier": {"value": "R01237"}})
        + "</script>"
    )
    source.checked.clear()
    deferred = asyncio.run(run({"R01234": original, "R01237": other}))
    assert deferred.complete and deferred.skipped == 0
    assert {item.external_id for item in deferred.listings} == {"R01234", "R01237"}


def test_shared_atos_feed_attributes_only_explicit_eviden_brand():
    data = b"""<rss xmlns:g="http://base.google.com/ns/1.0"><channel>
      <item><title>Stage logiciel (Paris, FR)</title><guid>1</guid>
        <link>https://jobs.atos.net/job/1/</link><g:location>Paris, FR</g:location>
        <description>&lt;p&gt;Bienvenue chez Eviden.&lt;/p&gt;</description>
      </item>
      <item><title>Stage cyber (Paris, FR)</title><guid>2</guid>
        <link>https://jobs.atos.net/job/2/</link><g:location>Paris, FR</g:location>
        <description>Atos Group exerce ses activites sous deux marques : Atos et Eviden.</description>
      </item>
    </channel></rss>"""
    batch = SuccessFactors("atos", "Atos").parse(data)
    assert [offer.employer for offer in batch.listings] == ["Eviden", "Atos"]


def test_thales_recent_publication_boundary():
    from datetime import UTC, timedelta
    from types import SimpleNamespace

    from stageradar.collectors.thales import recent_publication

    cutoff = datetime(2026, 11, 1, tzinfo=UTC)
    for date, expected in [
        (None, False),
        (cutoff, False),
        (cutoff - timedelta(seconds=1), False),
        (cutoff + timedelta(days=1), True),
        (cutoff + timedelta(days=16), False),
    ]:
        assert recent_publication(SimpleNamespace(published_at=date), cutoff) is expected
        assert (
            recent_publication(SimpleNamespace(published_at=date), cutoff.replace(tzinfo=None))
            is expected
        )
