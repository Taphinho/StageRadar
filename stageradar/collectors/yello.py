import asyncio
import re
from dataclasses import dataclass, field
from itertools import count as page_numbers
from typing import ClassVar
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_bytes, fetch_json
from stageradar.schemas import ListingInput
from stageradar.scoring import INTERNSHIP, matched, normalize

ORIGIN = "https://eyglobal.yello.co"
BOARD = "c1riT--B2O-KySgYWsZO1Q"
DETAIL_LIMIT = 24


@dataclass(slots=True)
class YelloEY:
    key: ClassVar[str] = "career:ey"
    label: ClassVar[str] = "EY"
    min_interval_minutes: ClassVar[int] = 120
    checked: set[str] = field(default_factory=set, init=False)

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        candidates = {}
        fetched = 0
        complete = False
        for page in page_numbers(1):
            payload = await fetch_json(
                client,
                f"{ORIGIN}/job_boards/{BOARD}/search",
                self.label,
                # The public board publishes France as filter answer 29994.
                {"locale": "fr", "query": "", "filters": "29994", "page_number": page},
            )
            html = payload.get("html")
            count = payload.get("count_on_page")
            more = payload.get("more_requisitions")
            if not isinstance(html, str) or type(count) is not int or type(more) is not bool:
                raise SourceError("Pagination EY non reconnue.")
            rows = BeautifulSoup(html, "html.parser").select("li.search-results__item")
            if len(rows) != count or more and count == 0:
                raise SourceError("Pagination EY incohérente.")
            fetched += count
            for row in rows:
                link = row.select_one("a.search-results__req_title[href]")
                if link is None:
                    raise SourceError("Résultat EY sans fiche.")
                path = urlsplit(link["href"]).path
                if not re.fullmatch(r"/jobs/[A-Za-z0-9_-]{1,100}", path):
                    raise SourceError("Identifiant de fiche EY non reconnu.")
                if matched(normalize(link.get_text(" ", strip=True)), INTERNSHIP):
                    candidates[path.rsplit("/", 1)[-1]] = path
            if not more:
                complete = True
                break
            await asyncio.sleep(0.25)

        self.checked.intersection_update(candidates)
        fresh = [key for key in candidates if key not in previous]
        refresh = [key for key in candidates if key in previous and key not in self.checked]
        if not refresh:
            self.checked.clear()
            refresh = [key for key in candidates if key in previous]
        queue = fresh + refresh
        listings = {key: previous[key] for key in candidates if key in previous}
        skipped = 0
        for identifier in queue:
            path = candidates[identifier]
            await asyncio.sleep(0.25)
            data = await fetch_bytes(
                client, ORIGIN + path, self.label, {"job_board_id": BOARD, "locale": "fr"}
            )
            try:
                listings[identifier] = self.parse_job(data, identifier)
                self.checked.add(identifier)
            except (AttributeError, KeyError, TypeError, ValueError):
                skipped += 1
        return Batch(
            list(listings.values()),
            skipped,
            complete=complete and not skipped,
            fetched=fetched,
            authoritative=False,
        )

    def parse_job(self, data: bytes, identifier: str) -> ListingInput:
        page = BeautifulSoup(data, "html.parser")
        title = page.select_one(".details-top__jobtitle h1")
        description = page.select_one(".job-details__description")
        header = page.select_one(".details-top__jobtitle")
        if title is None or description is None or header is None:
            raise ValueError("Fiche EY sans description.")
        location = " · ".join(
            span.get_text(" ", strip=True)
            for span in header.select("span")
            if not span.get_text(" ", strip=True).isdigit()
        )
        return ListingInput(
            external_id=identifier,
            employer=self.label,
            title=title.get_text(" ", strip=True),
            description=str(description),
            location=location or None,
            original_url=f"{ORIGIN}/jobs/{identifier}?job_board_id={BOARD}&locale=fr",
            # The displayed list date omits the year. Preserve an unknown publication date.
            published_at=None,
        )
