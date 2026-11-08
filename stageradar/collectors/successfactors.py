import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html import unescape
from io import BytesIO
from typing import ClassVar
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_bytes
from stageradar.schemas import ListingInput

HOSTS = {
    "capgemini": "careers.capgemini.com",
    "arkema": "jobs.arkema.com",
    "bouygues": "careers.bouyguestelecom.fr",
    "atos": "jobs.atos.net",
}
GOOGLE = "{http://base.google.com/ns/1.0}"


@dataclass(frozen=True, slots=True)
class SuccessFactors:
    board: str
    label: str

    # The verified feeds advertise a twelve-hour TTL.
    min_interval_minutes: ClassVar[int] = 720

    @property
    def key(self) -> str:
        return f"successfactors:{self.board}"

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        url = f"https://{HOSTS[self.board]}/sitemal.xml"
        data = await fetch_bytes(
            client, url, "SuccessFactors", max_body=96 * 1024 * 1024, total_timeout=60
        )
        return self.parse(data)

    def parse(self, data: bytes) -> Batch:
        # For these UTF-8 feeds, reject DTDs and encodings that could hide the declaration.
        if b"<!DOCTYPE" in data or b"\x00" in data:
            raise SourceError("Flux RSS SuccessFactors non valide.")
        listings: list[ListingInput] = []
        ids: set[str] = set()
        fetched = skipped = 0
        parents: list[ElementTree.Element] = []
        try:
            events = ElementTree.iterparse(BytesIO(data), events=("start", "end"))
            for event, element in events:
                if event == "start":
                    parents.append(element)
                    continue
                if len(parents) == 3 and parents[1].tag == "channel" and element.tag == "item":
                    fetched += 1
                    try:
                        listing = self._listing(element)
                        if listing and listing.external_id not in ids:
                            ids.add(listing.external_id)
                            listings.append(listing)
                    except (TypeError, ValueError, OverflowError):
                        skipped += 1
                    parents[1].remove(element)
                parents.pop()
        except ElementTree.ParseError:
            raise SourceError("Flux RSS SuccessFactors non valide.") from None
        if events.root.tag != "rss" or events.root.find("channel") is None:
            raise SourceError("Flux RSS SuccessFactors sans canal.")
        return Batch(listings, skipped, complete=not skipped, fetched=fetched, authoritative=False)

    def _listing(self, row: ElementTree.Element) -> ListingInput | None:
        location = (row.findtext(GOOGLE + "location") or "").strip()
        if not re.search(r"(?:^|,)\s*FR(?:\s*,\s*\d{5})?$", location, re.IGNORECASE):
            return None
        title = row.findtext("title") or ""
        key = row.findtext("guid") or row.findtext(GOOGLE + "id") or ""
        published = row.findtext("pubDate")
        description = row.findtext("description") or ""
        employer = self.label
        if self.board == "atos":
            introduction = BeautifulSoup(unescape(description[:8000]), "html.parser").get_text(
                " ", strip=True
            )
            if re.search(
                r"\b(?:bienvenue chez|welcome to|about|[àa] propos d['’]|rejoignez)\s*Eviden\b",
                introduction[:1200],
                re.IGNORECASE,
            ):
                employer = "Eviden"
        return ListingInput(
            external_id=key,
            employer=employer,
            title=title.strip().removesuffix(f" ({location})"),
            description=description,
            original_url=(row.findtext("link") or "").strip(),
            location=location,
            published_at=parsedate_to_datetime(published) if published else None,
        )
