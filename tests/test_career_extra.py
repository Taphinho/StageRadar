import asyncio
import json
from datetime import datetime

import httpx

from stageradar.collectors.bpce import BPCE
from stageradar.collectors.dassault import Dassault
from stageradar.collectors.njoyn import CGI


def test_dassault_reads_escaped_graph_and_exact_publication():
    record = {
        "@graph": [
            {
                "@type": "JobPosting",
                "identifier": "1234",
                "title": "Stage cybersécurité",
                "datePosted": "2026-11-06T06:09:00Z",
                "jobLocation": {
                    "address": {"addressCountry": "France", "addressLocality": "Vélizy"}
                },
                "description": "Stage",
                "employmentType": "Temps plein",
            }
        ]
    }
    escaped = json.dumps(json.dumps(record, ensure_ascii=False))[1:-1]
    raw = f'<script type="application/ld+json">{escaped}</script>'
    item = Dassault().parse_job(raw.encode(), "1234", "https://www.3ds.com/careers/jobs/stage-1234")
    assert item.external_id == "1234"
    assert item.title == "Stage cybersécurité"
    assert item.published_at == datetime(2026, 11, 6, 6, 9)
    assert item.contract is None


def test_cgi_reads_job_id_not_shared_portal_id():
    record = {
        "@type": "JobPosting",
        "title": "Stage Cloud",
        "identifier": {"value": "21001"},
        "datePosted": "2026-11-06",
        "jobLocation": {"address": {"addressCountry": "FR ", "addressLocality": "Paris"}},
        "employmentType": "INTERN",
        "description": "Introduction",
    }
    raw = (
        '<script type="application/ld+json">'
        + json.dumps(record)
        + '</script><div class="job-posting-content"><p>Missions détaillées.</p></div>'
    )
    item = CGI().parse_job(raw.encode(), "J1126-001", "https://cgi.njoyn.com/corp/xweb/xweb.asp")
    assert item.external_id == "J1126-001"
    assert "Missions détaillées" in item.description
    assert item.published_at == datetime(2026, 11, 6)


def test_bpce_uses_public_france_stage_search_and_original_date():
    def handle(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, content=b"User-agent: *\nDisallow: /emploi/\nDisallow: /cat\xe9gorie/\n"
            )
        assert request.url.host == "recrutement.bpce.fr"
        payload = json.loads(request.content)
        assert payload["tax_contract"] == "stage,stage-sup-a-2-mois"
        assert payload["tax_country"] == "france"
        return httpx.Response(
            200,
            json={
                "data": {
                    "total": 1,
                    "items": [
                        {
                            "post_id": 42,
                            "title": "Stage cyber",
                            "description": "Stage de 6 mois.",
                            "date": "2026-11-02",
                            "modification_date": 1794150605,
                            "link": {"url": "/job/stage-cyber"},
                            "contract": ["Stage"],
                            "localisations": [{"city": "Paris", "country": "France"}],
                        }
                    ],
                }
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await BPCE().fetch(client, {})

    batch = asyncio.run(run())
    assert batch.complete
    assert batch.listings[0].published_at == datetime(2026, 11, 2)
    assert batch.listings[0].location == "Paris, France"


def test_bnp_ignores_closed_offers_and_keeps_original_date():
    from stageradar.collectors.bnp import BNP

    record = {
        "@type": "JobPosting",
        "identifier": {"value": "ITG123"},
        "title": "Stage cyber",
        "description": "<p>Stage de 6 mois.</p>",
        "employmentType": "Stage",
        "datePosted": "2026-11-06",
        "jobLocation": {"address": {"addressCountry": "FR", "addressLocality": "Paris"}},
    }
    raw = '<script type="application/ld+json">' + json.dumps(record) + "</script>"
    source = BNP()
    url = "https://group.bnpparibas/emploi-carriere/offre-emploi/stage-cyber"
    item = source.parse_job(raw.encode(), url)
    assert item.external_id == "ITG123"
    assert item.published_at == datetime(2026, 11, 6)
    closed = '<div class="offer-apply"><span class="cta-inactive">Offre pourvue</span></div>'
    assert source.parse_job((raw + closed).encode(), url) is None
