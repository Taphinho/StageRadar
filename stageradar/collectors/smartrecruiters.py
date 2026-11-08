import asyncio
import re
from dataclasses import dataclass

import httpx

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_json
from stageradar.schemas import ListingInput
from stageradar.scoring import IDF, INTERNSHIP, matched, normalize

PROVIDER = "SmartRecruiters"
PAGE_SIZE = 100
MAX_PAGES = 25
MAX_DETAILS = 24


@dataclass(frozen=True, slots=True)
class SmartRecruiters:
    company: str
    label: str
    nationwide: bool = False

    @property
    def key(self) -> str:
        return f"smartrecruiters:{self.company}"

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        url = f"https://api.smartrecruiters.com/v1/companies/{self.company}/postings"
        listings: list[ListingInput] = []
        candidates: list[tuple[str, str | None, bool]] = []
        skipped = 0
        fetched = 0
        complete = False
        seen_ids: set[str] = set()
        for page in range(MAX_PAGES):
            payload = await fetch_json(
                client,
                url,
                PROVIDER,
                {
                    "destination": "PUBLIC",
                    "country": "fr",
                    "limit": PAGE_SIZE,
                    "offset": page * PAGE_SIZE,
                },
            )
            rows, total = payload.get("content"), payload.get("totalFound")
            if not isinstance(rows, list) or type(total) is not int:
                raise SourceError("Réponse SmartRecruiters sans pagination valide.")
            fetched += len(rows)
            for row in rows:
                try:
                    posting_id = row["id"]
                    if not isinstance(posting_id, str) or not re.fullmatch(
                        r"[0-9]{1,40}", posting_id
                    ):
                        raise ValueError
                    if posting_id in seen_ids:
                        skipped += 1
                        continue
                    seen_ids.add(posting_id)
                    title = normalize(row["name"])
                    contract = (row.get("typeOfEmployment") or {}).get("id")
                    location = row.get("location") or {}
                    regional = (
                        matched(normalize(location.get("region") or ""), "idf|ile de france")
                        or matched(normalize(location.get("city") or ""), IDF)
                        or bool(
                            re.fullmatch(
                                r"(?:75|77|78|91|92|93|94|95)\d{3}",
                                location.get("postalCode") or "",
                            )
                        )
                    )
                    if (regional or self.nationwide) and (
                        matched(title, INTERNSHIP) or contract in {"intern", "internship"}
                    ):
                        candidates.append((posting_id, row.get("releasedDate"), regional))
                except (AttributeError, KeyError, TypeError, ValueError):
                    skipped += 1
            if fetched >= total:
                complete = fetched == total
                break
            if len(rows) != PAGE_SIZE:
                break
            await asyncio.sleep(0.25)

        details = 0
        for posting_id, released, _ in sorted(candidates, key=lambda item: not item[2]):
            old = previous.get(posting_id)
            if old and old.description.strip() and isinstance(released, str) and old.published_at:
                if old.published_at.isoformat(timespec="milliseconds") == released.removesuffix(
                    "Z"
                ):
                    listings.append(old)
                    continue
            if details >= MAX_DETAILS:
                skipped += 1
                continue
            details += 1
            await asyncio.sleep(0.25)
            try:
                row = await fetch_json(client, f"{url}/{posting_id}", PROVIDER)
                location = row["location"]
                sections = row["jobAd"]["sections"]
                paragraphs = []
                for name in (
                    "companyDescription",
                    "jobDescription",
                    "qualifications",
                    "additionalInformation",
                ):
                    section = sections.get(name)
                    content = section.get("text") if isinstance(section, dict) else section
                    if isinstance(content, str) and content.strip():
                        paragraphs.append(content)
                description = "\n".join(paragraphs)
                contract = (row.get("typeOfEmployment") or {}).get("id")
                listings.append(
                    ListingInput(
                        external_id=posting_id,
                        employer=self.label,
                        title=row["name"],
                        location=location.get("fullLocation") or location.get("city"),
                        description=description,
                        contract="Intern" if contract in {"intern", "internship"} else None,
                        remote="hybride"
                        if location.get("hybrid")
                        else "télétravail"
                        if location.get("remote")
                        else None,
                        original_url=row["postingUrl"],
                        apply_url=row.get("applyUrl"),
                        published_at=row.get("releasedDate"),
                    )
                )
            except SourceError as exc:
                if exc.retry_after:
                    raise
                skipped += 1
            except (AttributeError, KeyError, TypeError, ValueError):
                skipped += 1
        return Batch(listings, skipped, complete=complete and not skipped, fetched=fetched)
