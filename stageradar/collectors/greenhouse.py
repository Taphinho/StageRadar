from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_json
from stageradar.schemas import ListingInput


@dataclass(frozen=True, slots=True)
class Greenhouse:
    board: str
    label: str

    @property
    def key(self) -> str:
        return f"greenhouse:{self.board}"

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.board}/jobs"
        payload = await fetch_json(client, url, "Greenhouse", {"content": "true"})
        return self._parse(payload)

    def _parse(self, payload: object) -> Batch:
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise SourceError("Réponse Greenhouse sans tableau d’offres.")
        listings: list[ListingInput] = []
        skipped = 0
        for row in payload["jobs"]:
            try:
                if type(row["id"]) is not int:
                    raise ValueError
                content = row["content"]
                if not isinstance(content, str):
                    raise ValueError
                listings.append(
                    ListingInput(
                        external_id=str(row["id"]),
                        employer=self.label,
                        title=row["title"],
                        description=content,
                        location=(row.get("location") or {}).get("name"),
                        original_url=row["absolute_url"],
                        apply_url=row["absolute_url"],
                        published_at=row.get("first_published"),
                    )
                )
            except (AttributeError, KeyError, TypeError, ValueError, ValidationError):
                skipped += 1
        if skipped and not listings:
            raise SourceError("Aucune offre Greenhouse au format attendu.")
        total = (
            (payload.get("meta") or {}).get("total")
            if isinstance(payload.get("meta"), dict)
            else None
        )
        return Batch(
            listings, skipped, complete=not skipped and (total is None or total == len(listings))
        )
