import asyncio

import httpx

from stageradar.collectors import yello


def test_ey_paginates_france_and_fetches_only_stage_details(monkeypatch):
    async def skip_sleep(_):
        pass

    monkeypatch.setattr(yello.asyncio, "sleep", skip_sleep)
    pages = []

    def respond(request):
        assert request.url.host == "eyglobal.yello.co"
        if request.url.path.endswith("/search"):
            assert request.url.params["filters"] == "29994"
            page = int(request.url.params["page_number"])
            pages.append(page)
            title = "Consultant confirmé" if page == 1 else "Stage Consultant cyber"
            return httpx.Response(
                200,
                json={
                    "html": f'<li class="search-results__item"><a class="search-results__req_title" href="/jobs/test-{page}">{title}</a></li>',
                    "count_on_page": 1,
                    "more_requisitions": page == 1,
                },
            )
        assert request.url.path == "/jobs/test-2"
        return httpx.Response(
            200,
            text='<div class="details-top__jobtitle"><h1>Stage Consultant cyber</h1><span>1234</span><span>FRA-Paris La Défense</span></div><section class="job-details__description"><p>Stage 6 mois. Sécurité cloud.</p></section>',
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await yello.YelloEY().fetch(client, {})

    batch = asyncio.run(run())
    assert pages == [1, 2]
    assert batch.complete and batch.fetched == 2 and len(batch.listings) == 1
    assert batch.listings[0].location == "FRA-Paris La Défense"
    assert batch.listings[0].published_at is None
    assert "Sécurité cloud" in batch.listings[0].description
