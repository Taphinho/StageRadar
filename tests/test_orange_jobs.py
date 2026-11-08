import asyncio
import json
from datetime import datetime

import httpx
import pytest

from stageradar.collectors.base import SourceError
from stageradar.collectors.orange_jobs import ORIGIN, OrangeJobs, sitemap_paths


def job_page(*, company="Orange Cyberdefense", date="Oct 21, 2026", country="FRANCE"):
    job_id = "IOS-2026-2797"
    description = f"<p>Date de publication : {date}, 12:00AM</p><p>Stage cyber de 6 mois.</p>"
    record = {
        "@type": "JobPosting",
        "identifier": {"value": job_id},
        "title": "Stage - Cyber Lab",
        "datePosted": "2026-11-08",
        "jobLocation": {"address": {"addressCountry": country, "addressLocality": "Puteaux"}},
        "description": description,
    }
    embedded = {
        "jobDetail": {
            "data": {
                "job": {
                    "jobId": job_id,
                    "company": company,
                    "contractType": "Stage",
                    "description": description,
                    "postedDate": "2026-11-08T13:23:45.000+0000",
                }
            }
        }
    }
    return (
        f'<script type="application/ld+json">{json.dumps(record)}</script>'
        f"<script>phApp.ddo = {json.dumps(embedded)};</script>"
    ).encode()


def test_orange_jobs_preserves_original_publication_date_and_company():
    source = OrangeJobs()
    item = source.parse_job(job_page(), "IOS-2026-2797", "/fr/fr/job/IOS-2026-2797/Stage-Cyber-Lab")
    assert item.employer == "Orange Cyberdefense"
    assert item.published_at == datetime(2026, 10, 21)
    assert item.location == "Puteaux, France"
    assert item.contract == "Stage"
    other = source.parse_job(
        job_page(company="Orange Business", date="non renseignée"),
        "IOS-2026-2797",
        "/fr/fr/job/IOS-2026-2797/Stage-Cyber-Lab",
    )
    assert other.employer == "Orange"
    assert other.published_at is None
    assert (
        source.parse_job(
            job_page(country="ES"), "IOS-2026-2797", "/fr/fr/job/IOS-2026-2797/Stage-Cyber-Lab"
        )
        is None
    )


def test_orange_jobs_sitemap_gets_only_same_origin_stage_pages_and_refreshes(monkeypatch):
    async def skip_wait(_delay):
        pass

    monkeypatch.setattr("stageradar.collectors.orange_jobs.asyncio.sleep", skip_wait)
    namespace = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    paths = {
        "/robots.txt": b"User-agent: *\nDisallow: */apply\n",
        "/fr/fr/sitemap_index.xml": (
            f"<sitemapindex {namespace}>"
            f"<sitemap><loc>{ORIGIN}/fr/fr/sitemap1.xml</loc></sitemap>"
            "<sitemap><loc>https://example.org/fr/fr/sitemap2.xml</loc></sitemap>"
            "</sitemapindex>"
        ).encode(),
        "/fr/fr/sitemap1.xml": (
            f"<urlset {namespace}>"
            f"<url><loc>{ORIGIN}/fr/fr/job/IOS-2026-2797/Stage-Cyber-Lab</loc></url>"
            f"<url><loc>{ORIGIN}/fr/fr/job/IOS-2026-9999/Ingenieur-CDI</loc></url>"
            "<url><loc>https://example.org/fr/fr/job/IOS-2026-9998/Stage-Cyber</loc></url>"
            "</urlset>"
        ).encode(),
        "/fr/fr/job/IOS-2026-2797": job_page(),
    }

    def respond(request):
        assert request.url.host == "orange.jobs"
        return httpx.Response(200, content=paths[request.url.path])

    source = OrangeJobs()

    async def run(previous):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await source.fetch(client, previous)

    batch = asyncio.run(run({}))
    assert batch.complete and not batch.authoritative
    assert batch.fetched == 1
    assert batch.listings[0].external_id == "IOS-2026-2797"
    paths["/fr/fr/job/IOS-2026-2797"] = job_page(date="Nov 01, 2026")
    refreshed = asyncio.run(run({"IOS-2026-2797": batch.listings[0]}))
    assert refreshed.listings[0].published_at == datetime(2026, 11, 1)


def test_orange_jobs_rejects_non_xml_sitemap():
    with pytest.raises(SourceError, match="Sitemap Orange Jobs"):
        sitemap_paths(b"<html></html>", "sitemapindex", "sitemap", r".*")
