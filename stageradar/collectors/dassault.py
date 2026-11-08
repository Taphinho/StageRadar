import asyncio
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_bytes
from stageradar.schemas import ListingInput
from stageradar.scoring import INTERNSHIP, matched, normalize

ORIGIN = "https://www.3ds.com"
TECH = "cyber|securite|security|cloud|data|logiciel|developpement|ia"


@dataclass(slots=True)
class Dassault:
    key = "career:dassault"
    label = "Dassault Systèmes"
    min_interval_minutes = 120
    checked: set[str] = field(default_factory=set, init=False)
    ignored: set[str] = field(default_factory=set, init=False)

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        data = await fetch_bytes(client, ORIGIN + "/sitemap/sitemap-careers.xml", self.label)
        try:
            if b"<!DOCTYPE" in data or b"\x00" in data:
                raise ValueError
            root = ElementTree.fromstring(data)
            if root.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset":
                raise ValueError
        except (ValueError, ElementTree.ParseError):
            raise SourceError("Sitemap Dassault Systèmes non reconnu.") from None
        candidates = {}
        for node in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
            url = urlsplit(node.text or "")
            match = re.fullmatch(r"/careers/jobs/[^/?#]+-(\d+)", url.path)
            if url.scheme == "https" and url.netloc == "www.3ds.com" and match and not url.query:
                if matched(normalize(url.path), INTERNSHIP):
                    candidates[match[1]] = url.path
        self.checked.intersection_update(candidates)
        self.ignored.intersection_update(candidates)
        order = sorted(
            candidates.keys() - self.ignored,
            key=lambda key: (matched(normalize(candidates[key]), TECH), key),
            reverse=True,
        )
        fresh = [key for key in order if key not in previous]
        refresh = [key for key in order if key in previous and key not in self.checked]
        if not refresh:
            self.checked.clear()
            refresh = [key for key in order if key in previous]
        queue = fresh + refresh
        skipped = 0
        listings = dict(previous)
        for key in queue:
            try:
                data = await fetch_bytes(client, ORIGIN + candidates[key], self.label)
                item = self.parse_job(data, key, ORIGIN + candidates[key])
                if item:
                    listings[key] = item
                    self.checked.add(key)
                else:
                    self.ignored.add(key)
            except SourceError as exc:
                if exc.retry_after:
                    raise
                skipped += 1
            except (ValueError, TypeError, KeyError, AttributeError):
                skipped += 1
            await asyncio.sleep(0.25)
        return Batch(
            list(listings.values()),
            skipped,
            complete=not skipped,
            fetched=len(candidates),
            authoritative=False,
        )

    def parse_job(self, data: bytes, identifier: str, url: str) -> ListingInput | None:
        page = BeautifulSoup(data, "html.parser")
        for script in page.select('script[type="application/ld+json"]'):
            text = (script.string or "").strip()
            try:
                if text.startswith(r"{\""):
                    text = json.loads('"' + text + '"')
                payload = json.loads(text)
            except (ValueError, RecursionError):
                continue
            records = payload.get("@graph", [payload]) if isinstance(payload, dict) else []
            for record in records:
                if (
                    record.get("@type") != "JobPosting"
                    or str(record.get("identifier")) != identifier
                ):
                    continue
                places = record.get("jobLocation") or []
                locations = []
                for place in places if isinstance(places, list) else [places]:
                    address = place.get("address") or {}
                    country = address.get("addressCountry") or ""
                    if isinstance(country, dict):
                        country = country.get("name", "")
                    if normalize(str(country)) in {"fr", "france"}:
                        locations.append(address.get("addressLocality") or "France")
                if not locations:
                    return None
                description = page.select_one(".jobdetails-body-container")
                return ListingInput(
                    external_id=identifier,
                    employer=self.label,
                    title=record["title"],
                    description=str(description) if description else record.get("description", ""),
                    location=" · ".join(dict.fromkeys(locations)) + ", France",
                    original_url=url,
                    # The portal's contract metadata says full-time even for internships.
                    published_at=record.get("datePosted"),
                )
        raise ValueError("Fiche Dassault Systèmes sans JobPosting correspondant.")
