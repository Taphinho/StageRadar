import asyncio
import json
import re
from dataclasses import dataclass, field
from html import unescape
from itertools import count as page_numbers
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_bytes
from stageradar.schemas import ListingInput
from stageradar.scoring import matched, normalize

ORIGIN = "https://group.bnpparibas"
INDEX = "/emploi-carriere/toutes-offres-emploi"
PREFIX = "/emploi-carriere/offre-emploi/"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "fr-FR,fr;q=0.9"}
TECH = "cyber|securite|security|cloud|data|informatique|developpement|reseaux"


@dataclass(slots=True)
class BNP:
    key = "career:bnp"
    label = "BNP Paribas"
    min_interval_minutes = 120
    next_page: int = field(default=1, init=False)
    checked: set[str] = field(default_factory=set, init=False)
    ignored: set[str] = field(default_factory=set, init=False)

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        candidates = {}
        max_page = 1
        for number in page_numbers(1):
            if number > max_page:
                break
            raw = await fetch_bytes(
                client,
                ORIGIN + INDEX,
                self.label,
                {"form[type][]": "28", "page": str(number)},
                headers=HEADERS,
            )
            page = BeautifulSoup(raw, "html.parser")
            anchors = page.select(f'a[href^="{PREFIX}"]')
            if not anchors:
                raise SourceError("BNP Paribas : liste de stages non reconnue.")
            for anchor in anchors:
                url = urlsplit(anchor["href"])
                if url.netloc or not url.path.startswith(PREFIX):
                    continue
                text = normalize(anchor.get_text(" ", strip=True))
                candidates[url.path] = matched(text, TECH), "france" in text, text
            for anchor in page.select("a[href]"):
                match = re.search(r"[?&]page=(\d+)", anchor["href"])
                if match:
                    max_page = max(max_page, int(match[1]))
            await asyncio.sleep(0.25)
        self.next_page = self.next_page + 4 if self.next_page + 4 <= max_page else 1
        self.ignored.intersection_update(candidates)
        known = {urlsplit(str(item.original_url)).path for item in previous.values()}
        order = sorted(
            candidates.keys() - self.ignored, key=lambda path: candidates[path], reverse=True
        )
        fresh = [path for path in order if path not in known]
        refresh = [path for path in order if path in known and path not in self.checked]
        if not refresh:
            self.checked.clear()
            refresh = [path for path in order if path in known]
        queue = fresh + refresh
        skipped = 0
        listings = dict(previous)
        for path in queue:
            try:
                raw = await fetch_bytes(client, ORIGIN + path, self.label, headers=HEADERS)
                item = self.parse_job(raw, ORIGIN + path)
                if item:
                    listings[item.external_id] = item
                    self.checked.add(path)
                else:
                    self.ignored.add(path)
            except SourceError as exc:
                if exc.retry_after:
                    raise
                skipped += 1
            except (ValueError, KeyError, TypeError, AttributeError):
                skipped += 1
            await asyncio.sleep(0.25)
        return Batch(
            list(listings.values()),
            skipped,
            complete=not skipped,
            fetched=len(candidates),
            authoritative=False,
        )

    def parse_job(self, data: bytes, url: str) -> ListingInput | None:
        page = BeautifulSoup(data, "html.parser")
        if page.select_one(".offer-apply .cta-inactive"):
            return None
        for script in page.select('script[type="application/ld+json"]'):
            try:
                record = json.loads(script.string or "")
            except (ValueError, RecursionError):
                continue
            if not isinstance(record, dict) or record.get("@type") != "JobPosting":
                continue
            address = record["jobLocation"]["address"]
            if normalize(address.get("addressCountry", "")) not in {"fr", "france"}:
                return None
            return ListingInput(
                external_id=record["identifier"]["value"],
                employer=self.label,
                title=unescape(record["title"]),
                description=record.get("description") or "",
                location=", ".join(
                    filter(
                        None,
                        (address.get("addressLocality"), address.get("addressRegion"), "France"),
                    )
                ),
                original_url=url,
                contract=record.get("employmentType"),
                published_at=record.get("datePosted"),
            )
        raise ValueError("Fiche BNP Paribas sans JobPosting.")
