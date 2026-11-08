import asyncio
from dataclasses import dataclass
from html import unescape
from urllib.robotparser import RobotFileParser

import httpx

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_bytes, fetch_json
from stageradar.schemas import ListingInput

ORIGIN = "https://recrutement.bpce.fr"
SEARCH = "/app/wp-json/bpce/v1/search/jobs"
PAGE_SIZE = 50


@dataclass(frozen=True, slots=True)
class BPCE:
    key = "career:bpce"
    label = "BPCE"
    min_interval_minutes = 120

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        robots = RobotFileParser()
        robots.parse(
            (await fetch_bytes(client, ORIGIN + "/robots.txt", self.label))
            .decode("utf-8", errors="replace")
            .splitlines()
        )
        if not robots.can_fetch("StageRadar", ORIGIN + SEARCH):
            raise SourceError("Recherche BPCE exclue par robots.txt.")
        listings = []
        seen = set()
        fetched = skipped = 0
        complete = False
        for page in range(15):
            data = await fetch_json(
                client,
                ORIGIN + SEARCH,
                self.label,
                method="POST",
                body={
                    "lang": "fr",
                    "tax_country": "france",
                    "tax_contract": "stage,stage-sup-a-2-mois",
                    "size": str(PAGE_SIZE),
                    "from": str(page * PAGE_SIZE),
                },
            )
            rows, total = data.get("data", {}).get("items"), data.get("data", {}).get("total")
            if not isinstance(rows, list) or type(total) is not int:
                raise SourceError("Recherche BPCE sans pagination valide.")
            fetched += len(rows)
            for row in rows:
                try:
                    identifier = str(row["post_id"])
                    if identifier in seen:
                        raise ValueError("Doublon BPCE.")
                    seen.add(identifier)
                    path = row["link"]["url"]
                    if (
                        not isinstance(path, str)
                        or not path.startswith("/job/")
                        or path.startswith("//")
                    ):
                        raise ValueError("Lien BPCE non reconnu.")
                    places = row.get("localisations") or []
                    location = " · ".join(
                        ", ".join(
                            filter(
                                None,
                                (
                                    place.get("city"),
                                    place.get("region"),
                                    place.get("country"),
                                ),
                            )
                        )
                        for place in places
                    )
                    listings.append(
                        ListingInput(
                            external_id=identifier,
                            employer=self.label,
                            title=unescape(row["title"]),
                            description=row.get("description") or "",
                            original_url=ORIGIN + path,
                            apply_url=(row.get("postulate_link") or {}).get("url") or ORIGIN + path,
                            contract=" · ".join(row.get("contract") or []) or None,
                            location=location or row.get("localisation"),
                            published_at=row.get("date"),
                            remote=row.get("teletravail") or None,
                        )
                    )
                except (ValueError, TypeError, KeyError, AttributeError):
                    skipped += 1
            if fetched >= total:
                complete = fetched == total
                break
            if len(rows) != PAGE_SIZE:
                break
            await asyncio.sleep(0.25)
        return Batch(listings, skipped, complete=complete and not skipped, fetched=fetched)
