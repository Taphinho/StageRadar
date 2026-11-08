import json
import re
from dataclasses import dataclass
from typing import ClassVar

import httpx

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_bytes, fetch_json, fetch_json_array
from stageradar.schemas import ListingInput


@dataclass(frozen=True, slots=True)
class Synetis:
    key: ClassVar[str] = "career:synetis"
    label: ClassVar[str] = "Synetis"
    min_interval_minutes: ClassVar[int] = 60

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        # This is the public embed called by Synetis' own career page.
        payload = await fetch_json(
            client,
            "https://www.welcomekit.co/api/v1/embed",
            self.label,
            {"organization_reference": "4lMLezr"},
        )
        rows = payload.get("jobs")
        if not isinstance(rows, list):
            raise SourceError("Liste d’offres Synetis absente.")
        listings = []
        seen = set()
        skipped = 0
        for row in rows:
            try:
                reference = row["reference"]
                slug = row["slug"]
                if (
                    not isinstance(reference, str)
                    or reference in seen
                    or not isinstance(slug, str)
                    or not re.fullmatch(r"[a-zA-Z0-9_-]+", slug)
                ):
                    raise ValueError
                offices = row.get("offices") or [row.get("office") or {}]
                locations = [
                    ", ".join(
                        filter(
                            None,
                            (
                                office.get("city"),
                                office.get("zip_code"),
                                office.get("country", {}).get("fr"),
                            ),
                        )
                    )
                    for office in offices
                ]
                listings.append(
                    ListingInput(
                        external_id=reference,
                        employer=self.label,
                        title=row["name"],
                        description="\n".join(
                            row.get(field) or ""
                            for field in ("description", "profile", "recruitment_process")
                        ),
                        contract=(row.get("contract_type") or {}).get("fr"),
                        location=" · ".join(dict.fromkeys(filter(None, locations))) or None,
                        original_url=f"https://synetis.welcomekit.co/jobs/{slug}",
                        published_at=row.get("published_at"),
                    )
                )
                seen.add(reference)
            except (AttributeError, KeyError, TypeError, ValueError):
                skipped += 1
        return Batch(listings, skipped, complete=not skipped, fetched=len(rows))


@dataclass(frozen=True, slots=True)
class Intrinsec:
    key: ClassVar[str] = "career:intrinsec"
    label: ClassVar[str] = "Intrinsec"
    min_interval_minutes: ClassVar[int] = 60

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        page = await fetch_bytes(
            client, "https://www.intrinsec.com/rejoindre-intrinsec/", self.label
        )
        match = re.search(rb"var\s+wp_boondmanager_globals\s*=\s*(\{[^\n]+\});", page)
        try:
            globals_ = json.loads(match[1]) if match else {}
            nonce = globals_["nonce"]
            if not isinstance(nonce, str) or not re.fullmatch(r"[a-zA-Z0-9]+", nonce):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise SourceError("Widget public Intrinsec non reconnu.") from None
        # The token is published with the widget and identifies its public read action.
        rows = await fetch_json_array(
            client,
            "https://www.intrinsec.com/wp-admin/admin-ajax.php",
            self.label,
            {"action": "get-opportunities", "_ajax_nonce": nonce},
        )
        listings = []
        seen = set()
        skipped = 0
        for row in rows:
            try:
                identifier = row["id"]
                if type(identifier) is not int or identifier <= 0 or identifier in seen:
                    raise ValueError
                seen.add(identifier)
                if row.get("state") != "published":
                    continue
                listings.append(
                    ListingInput(
                        external_id=str(identifier),
                        employer=self.label,
                        title=row["title"],
                        description="\n".join(
                            row.get(field) or "" for field in ("description", "criteria")
                        ),
                        contract=row.get("contract"),
                        location=row.get("place"),
                        original_url=f"https://www.intrinsec.com/offre-emploi?opportunity_id={identifier}",
                        apply_url=f"https://www.intrinsec.com/postuler?opportunity_id={identifier}",
                        published_at=row.get("datePosted"),
                    )
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                skipped += 1
        return Batch(listings, skipped, complete=not skipped, fetched=len(rows))
