import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_bytes
from stageradar.schemas import ListingInput

CUSTOM_HOSTS = {
    "orangecyberdefense": "jobs.orangecyberdefense.com",
    "almond": "careers.almond.eu",
    "vinci-energies": "youngtalentsdays.vinci-energies.com",
}
NS = {"tt": "https://teamtailor.com/locations"}
WORKPLACE = {"remote": "télétravail", "hybrid": "hybride", "onsite": "sur site"}


@dataclass(frozen=True, slots=True)
class Teamtailor:
    board: str
    label: str

    @property
    def key(self) -> str:
        return f"teamtailor:{self.board}"

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        host = CUSTOM_HOSTS.get(self.board, f"{self.board}.teamtailor.com")
        data = await fetch_bytes(client, f"https://{host}/jobs.rss", "Teamtailor")
        try:
            # The published RSS uses UTF-8. Reject DTDs and external entity declarations.
            xml = data.decode("utf-8-sig")
            if "<!DOCTYPE" in xml or "\x00" in xml:
                raise ValueError
            root = ElementTree.fromstring(xml)
        except (ValueError, ElementTree.ParseError):
            raise SourceError("Flux RSS Teamtailor non valide.") from None
        channel = root.find("channel") if root.tag == "rss" else None
        if channel is None:
            raise SourceError("Flux RSS Teamtailor sans canal.")
        rows = channel.findall("item")
        listings: list[ListingInput] = []
        skipped = 0
        ids: set[str] = set()
        for row in rows:
            try:
                key = row.findtext("guid")
                if not key or key in ids:
                    raise ValueError
                cities = dict.fromkeys(
                    filter(
                        None,
                        [
                            location.findtext("tt:city", namespaces=NS)
                            or location.findtext("tt:name", namespaces=NS)
                            for location in row.findall("tt:locations/tt:location", NS)
                        ],
                    )
                )
                date = row.findtext("pubDate")
                link = row.findtext("link")
                description = row.findtext("description") or ""
                employer = self.label
                if self.board == "vinci-energies":
                    introduction = BeautifulSoup(description[:8000], "html.parser").get_text(
                        " ", strip=True
                    )
                    if re.search(
                        r"^\W*axians\b|\b(?:rejoignez|chez|au sein d['’])\s*axians\b",
                        introduction[:1200],
                        re.IGNORECASE,
                    ):
                        employer = "Axians"
                listings.append(
                    ListingInput(
                        external_id=key,
                        employer=employer,
                        title=row.findtext("title"),
                        original_url=link,
                        apply_url=link,
                        description=description,
                        location=" · ".join(cities) or None,
                        published_at=parsedate_to_datetime(date) if date else None,
                        remote=WORKPLACE.get(row.findtext("remoteStatus")),
                    )
                )
                ids.add(key)
            except (ValueError, TypeError, OverflowError):
                skipped += 1
        return Batch(
            listings, skipped, complete=not skipped, fetched=len(rows), authoritative=False
        )
