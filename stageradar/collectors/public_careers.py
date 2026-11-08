import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_bytes
from stageradar.schemas import ListingInput
from stageradar.scoring import INTERNSHIP, matched, normalize

PORTALS = {
    "societegenerale": (
        "careers.societegenerale.com",
        "/fr/Technical/toutes-les-offres",
        "/offres-d-emploi/",
        ".blog-text",
    ),
    "creditagricole": (
        "groupecreditagricole.jobs",
        "/fr/nos-offres/",
        "/fr/nos-offres-emploi/",
        "article.offer",
    ),
}
TECH = "cyber|securite|security|informatique|cloud|devops|developpement|data|reseaux|analyste"
REGION = "paris|ile de france|la defense|montrouge|fontenay|courbevoie|guyancourt|palaiseau"


@dataclass(slots=True)
class PublicCareers:
    board: str
    label: str
    min_interval_minutes = 120
    next_page: int = field(default=1, init=False)
    checked: set[str] = field(default_factory=set, init=False)

    @property
    def key(self) -> str:
        return f"public:{self.board}"

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        host, index, prefix, selector = PORTALS[self.board]
        origin = f"https://{host}"
        paths = [index]
        if self.board == "creditagricole":
            paths = [f"{index}page/{i}/" for i in range(1, 2)]
        candidates = {}
        max_page = 1
        for position, path in enumerate(paths):
            if self.board == "creditagricole" and position and 1 + position > max_page:
                break
            page = BeautifulSoup(
                await fetch_bytes(client, origin + path, self.label), "html.parser"
            )
            cards = page.select(selector)
            if not cards:
                raise SourceError(f"{self.label} : liste d’offres non reconnue.")
            for card in cards:
                anchor = card.select_one("a[href]")
                if anchor is None:
                    continue
                url = urlsplit(anchor["href"])
                if url.scheme != "https" or url.netloc != host or not url.path.startswith(prefix):
                    continue
                text = normalize(card.get_text(" ", strip=True))
                if matched(text, INTERNSHIP) and matched(text, "france"):
                    candidates[url.path] = (matched(text, TECH), matched(text, REGION), text)
            for anchor in page.select("a[href]"):
                url = urlsplit(anchor["href"])
                match = re.fullmatch(re.escape(index) + r"page/(\d+)/", url.path)
                if url.netloc == host and match:
                    max_page = max(max_page, int(match[1]))
            if self.board == "creditagricole" and position + 1 == len(paths):
                paths.extend(f"{index}page/{i}/" for i in range(len(paths) + 1, max_page + 1))
            await asyncio.sleep(0.25)
        if self.board == "creditagricole":
            self.next_page = self.next_page + 4 if self.next_page + 4 <= max_page else 1

        listings = dict(previous)
        ordered = sorted(candidates, key=lambda path: candidates[path], reverse=True)
        known_paths = {urlsplit(str(item.original_url)).path: key for key, item in previous.items()}
        fresh = [path for path in ordered if path not in known_paths]
        refresh = [path for path in ordered if path in known_paths and path not in self.checked]
        if not refresh:
            self.checked.clear()
            refresh = [path for path in ordered if path in known_paths]
        queue = fresh + refresh
        skipped = 0
        for path in queue:
            try:
                data = await fetch_bytes(client, origin + path, self.label)
                item = self.parse_job(data, origin + path)
                if item is not None:
                    listings[item.external_id] = item
                    self.checked.add(path)
            except SourceError as exc:
                if exc.retry_after:
                    raise
                skipped += 1
            except (ValueError, TypeError, KeyError, AttributeError):
                skipped += 1
            if self.board == "creditagricole" and position + 1 == len(paths):
                paths.extend(f"{index}page/{i}/" for i in range(len(paths) + 1, max_page + 1))
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
        records = []
        for script in page.select('script[type="application/ld+json"]'):
            try:
                record = json.loads(script.string or "")
                records.extend(record if isinstance(record, list) else [record])
            except (ValueError, RecursionError):
                continue
        for record in records:
            if not isinstance(record, dict) or record.get("@type") != "JobPosting":
                continue
            places = record.get("jobLocation") or []
            locations = []
            for place in places if isinstance(places, list) else [places]:
                address = place.get("address") or {}
                country = address.get("addressCountry") or ""
                if isinstance(country, dict):
                    country = country.get("name", "")
                if normalize(str(country)) in {"fr", "france", "fra"}:
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
                return None
            published = record.get("datePosted")
            if published:
                pattern = "%Y/%m/%d" if self.board == "societegenerale" else "%d/%m/%Y"
                published = datetime.strptime(published, pattern)
            if self.board == "societegenerale":
                external_id = (record.get("identifier") or {})["value"]
                sections = [str(h.parent) for h in page.select("section > h2")]
                description = "\n".join(sections) or record.get("description", "")
            else:
                match = re.search(r"reference--([a-zA-Z0-9-]+)--", urlsplit(url).path)
                if not match:
                    raise ValueError("Référence Crédit Agricole absente.")
                external_id = match[1]
                description = record.get("description", "") + "\n" + record.get("skills", "")
            title = page.select_one("h1") if self.board == "societegenerale" else None
            return ListingInput(
                external_id=external_id,
                employer=self.label,
                title=unescape(title.get_text(" ", strip=True) if title else record["title"]),
                description=description,
                original_url=url,
                location=" · ".join(dict.fromkeys(locations)),
                contract=record.get("employmentType"),
                published_at=published,
            )
        raise ValueError("Fiche sans JobPosting.")
