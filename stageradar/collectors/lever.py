import asyncio
from dataclasses import dataclass
from html import escape

import httpx

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_json_array
from stageradar.schemas import ListingInput
from stageradar.scoring import INTERNSHIP, matched, normalize

PAGE_SIZE = 100
MAX_PAGES = 20
HOSTS = {"global": "api.lever.co", "eu": "api.eu.lever.co"}
WORKPLACE = {"remote": "télétravail", "hybrid": "hybride", "on-site": "sur site"}


@dataclass(frozen=True, slots=True)
class Lever:
    region: str
    board: str
    label: str

    @property
    def key(self) -> str:
        return f"lever:{self.region}:{self.board}"

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        url = f"https://{HOSTS[self.region]}/v0/postings/{self.board}"
        listings: list[ListingInput] = []
        ids: set[str] = set()
        fetched = skipped = 0
        for page in range(MAX_PAGES):
            rows = await fetch_json_array(
                client,
                url,
                "Lever",
                {
                    "mode": "json",
                    "limit": PAGE_SIZE,
                    "skip": page * PAGE_SIZE,
                },
            )
            fetched += len(rows)
            repeated = 0
            for row in rows:
                try:
                    posting_id = row["id"]
                    if not isinstance(posting_id, str) or not posting_id.strip():
                        raise ValueError
                    if posting_id in ids:
                        skipped += 1
                        repeated += 1
                        continue
                    ids.add(posting_id)
                    listings.append(self._parse(row))
                except (AttributeError, KeyError, TypeError, ValueError):
                    skipped += 1
            if len(rows) < PAGE_SIZE:
                if skipped and not listings:
                    raise SourceError("Aucune offre Lever au format attendu.")
                return Batch(listings, skipped, complete=not skipped, fetched=fetched)
            if repeated == len(rows):
                break
            await asyncio.sleep(0.25)
        return Batch(listings, skipped, fetched=fetched)

    def _parse(self, row: dict) -> ListingInput:
        categories = row.get("categories") or {}
        locations = dict.fromkeys(
            filter(
                None,
                [
                    categories.get("location"),
                    *(categories.get("allLocations") or []),
                ],
            )
        )
        commitment = categories.get("commitment") or ""
        sections = [row.get("description") or ""]
        for section in row.get("lists") or []:
            heading = escape(section.get("text") or "")
            sections.append(f"<h3>{heading}</h3><ul>{section.get('content') or ''}</ul>")
        sections.append(row.get("additional") or "")
        return ListingInput(
            external_id=row["id"],
            employer=self.label,
            title=row["text"],
            location=" · ".join(locations) or None,
            contract=commitment if matched(normalize(commitment), INTERNSHIP) else None,
            description="\n".join(filter(None, sections)),
            original_url=row["hostedUrl"],
            apply_url=row.get("applyUrl"),
            remote=WORKPLACE.get(row.get("workplaceType")),
        )
