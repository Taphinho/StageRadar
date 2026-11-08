from dataclasses import dataclass

import httpx

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_json
from stageradar.schemas import ListingInput
from stageradar.scoring import INTERNSHIP, matched, normalize

WORKPLACE = {"Remote": "télétravail", "Hybrid": "hybride", "OnSite": "sur site"}


@dataclass(frozen=True, slots=True)
class Ashby:
    board: str
    label: str

    @property
    def key(self) -> str:
        return f"ashby:{self.board}"

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        payload = await fetch_json(
            client, f"https://api.ashbyhq.com/posting-api/job-board/{self.board}", "Ashby"
        )
        rows = payload.get("jobs")
        if not isinstance(rows, list):
            raise SourceError("Réponse Ashby sans tableau d’offres.")
        listings: list[ListingInput] = []
        skipped = 0
        ids: set[str] = set()
        for row in rows:
            try:
                if row["isListed"] is False:
                    continue
                if row["isListed"] is not True:
                    raise ValueError
                posting_id = row.get("id")
                if posting_id is not None and (
                    not isinstance(posting_id, str) or not posting_id.strip()
                ):
                    raise ValueError
                # jobUrl is documented. Some boards may omit the optional ID.
                key = posting_id or row["jobUrl"]
                if key in ids:
                    raise ValueError
                locations = dict.fromkeys(
                    filter(
                        None,
                        [
                            row.get("location"),
                            *(
                                entry.get("location")
                                for entry in row.get("secondaryLocations") or []
                            ),
                        ],
                    )
                )
                employment = row.get("employmentType") or ""
                listings.append(
                    ListingInput(
                        external_id=key,
                        employer=self.label,
                        title=row["title"],
                        location=" · ".join(locations) or None,
                        contract=employment if matched(normalize(employment), INTERNSHIP) else None,
                        description=row.get("descriptionHtml") or row.get("descriptionPlain") or "",
                        original_url=row["jobUrl"],
                        apply_url=row.get("applyUrl"),
                        published_at=row.get("publishedAt"),
                        remote=WORKPLACE.get(row.get("workplaceType"))
                        or ("télétravail" if row.get("isRemote") is True else None),
                    )
                )
                ids.add(key)
            except (AttributeError, KeyError, TypeError, ValueError):
                skipped += 1
        return Batch(listings, skipped, complete=not skipped, fetched=len(rows))
