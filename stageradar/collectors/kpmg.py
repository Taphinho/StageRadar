import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import unquote, urlsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_bytes
from stageradar.schemas import ListingInput
from stageradar.scoring import IDF, INTERNSHIP, matched, normalize

ORIGIN = "https://emplois.kpmg.fr"
DETAIL_LIMIT = 24
TECH = "cyber|security|securite|audit des systemes|tech|cloud|data|informatique"


@dataclass(slots=True)
class KPMG:
    label = "KPMG"
    key = "kpmg:fr"
    min_interval_minutes = 120
    checked: set[str] = field(default_factory=set, init=False)

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        robots = RobotFileParser()
        robots.parse(
            (await fetch_bytes(client, ORIGIN + "/robots.txt", self.label)).decode().splitlines()
        )
        if not robots.can_fetch("StageRadar", ORIGIN + "/sitemap.xml"):
            raise SourceError("Sitemap KPMG exclu par robots.txt.")
        data = await fetch_bytes(client, ORIGIN + "/sitemap.xml", self.label)
        try:
            if b"<!DOCTYPE" in data or b"\x00" in data:
                raise ValueError
            root = ElementTree.fromstring(data)
            if root.tag != "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset":
                raise ValueError
        except (ValueError, ElementTree.ParseError):
            raise SourceError("Sitemap KPMG non valide.") from None
        candidates = []
        for element in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
            url = urlsplit(element.text or "")
            if (
                url.scheme != "https"
                or url.netloc != "emplois.kpmg.fr"
                or url.query
                or url.fragment
            ):
                continue
            if not re.fullmatch(r"/emploi/[^/]+/[^/]+/\d+/\d+", url.path):
                continue
            title = normalize(unquote(url.path))
            if matched(title, INTERNSHIP) and robots.can_fetch("StageRadar", ORIGIN + url.path):
                candidates.append(url.path)
        candidates = sorted(
            set(candidates),
            key=lambda path: (
                matched(normalize(unquote(path)), TECH),
                matched(normalize(unquote(path)), IDF),
                path,
            ),
            reverse=True,
        )
        known = {urlsplit(str(item.original_url)).path for item in previous.values()}
        self.checked.intersection_update(candidates)
        fresh = [path for path in candidates if path not in known]
        refresh = [path for path in candidates if path in known and path not in self.checked]
        if not refresh:
            self.checked.clear()
            refresh = [path for path in candidates if path in known]
        queue = fresh + refresh
        skipped = 0
        listings = dict(previous)
        checked = set()
        for path in queue:
            await asyncio.sleep(0.5)
            try:
                item = self.parse_job(
                    await fetch_bytes(client, ORIGIN + path, self.label), ORIGIN + path
                )
                listings[item.external_id] = item
                checked.add(path)
            except SourceError as exc:
                if exc.retry_after:
                    raise
                skipped += 1
            except (ValueError, TypeError, KeyError, AttributeError):
                skipped += 1
        self.checked.update(checked)
        return Batch(
            list(listings.values()),
            skipped,
            complete=not skipped,
            fetched=len(candidates),
            authoritative=False,
        )

    def parse_job(self, data: bytes, url: str) -> ListingInput:
        page = BeautifulSoup(data, "html.parser")
        for script in page.select('script[type="application/ld+json"]'):
            try:
                record = json.loads(script.string or "")
            except (ValueError, RecursionError):
                continue
            if not isinstance(record, dict) or record.get("@type") != "JobPosting":
                continue
            places = record.get("jobLocation") or []
            locations = []
            for place in places if isinstance(places, list) else [places]:
                address = place.get("address") or {}
                if normalize(str(address.get("addressCountry", ""))) not in {"fr", "france", "fra"}:
                    continue
                locations.append(
                    ", ".join(
                        filter(
                            None,
                            (
                                address.get("addressLocality"),
                                address.get("addressRegion"),
                                "France",
                            ),
                        )
                    )
                )
            if not locations:
                raise ValueError("Fiche KPMG sans localisation française.")
            return ListingInput(
                external_id=record["identifier"]["value"],
                employer=self.label,
                title=record["title"],
                description=record.get("description") or "",
                original_url=url,
                location=" · ".join(dict.fromkeys(locations)),
                contract=record.get("employmentType"),
                published_at=datetime.fromisoformat(record["datePosted"])
                if record.get("datePosted")
                else None,
            )
        raise ValueError("Fiche KPMG sans JobPosting.")
