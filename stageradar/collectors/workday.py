import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from itertools import count as page_numbers
from typing import ClassVar
from urllib.parse import unquote
from urllib.robotparser import RobotFileParser

import httpx

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_bytes, fetch_json
from stageradar.schemas import ListingInput
from stageradar.scoring import IDF, INTERNSHIP, matched, normalize

# Public external career sites verified without a candidate account.
WORKDAY_SITES = {
    "airbus": ("ag.wd3.myworkdayjobs.com", "ag", "Airbus"),
    "accenture": ("accenture.wd103.myworkdayjobs.com", "accenture", "AccentureCareers"),
    "deloitte": ("fina.wd103.myworkdayjobs.com", "fina", "DeloitteRecrute"),
    "pwc": ("pwc.wd3.myworkdayjobs.com", "pwc", "Global_Campus_Careers"),
    "onepoint": ("onepoint.wd3.myworkdayjobs.com", "onepoint", "OnepointFR"),
    "chanel": ("cc.wd3.myworkdayjobs.com", "cc", "ChanelCareers"),
}
FRANCE = "54c5b6971ffb4bf0b116fe7651ec789a"
PAGE_SIZE = 20
TECH = "cyber|security|securite|pentest|soc|iam|cloud|devops|informatique|software|data|ia"


@dataclass(slots=True)
class Workday:
    board: str
    label: str
    checked: set[str] = field(default_factory=set, init=False)
    ignored: set[str] = field(default_factory=set, init=False)
    min_interval_minutes: ClassVar[int] = 60

    @property
    def key(self) -> str:
        return f"workday:{self.board}"

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        host, tenant, site = WORKDAY_SITES[self.board]
        origin = f"https://{host}"
        base = f"{origin}/wday/cxs/{tenant}/{site}"
        robots = RobotFileParser()
        robots.parse(
            (await fetch_bytes(client, origin + "/robots.txt", "Workday")).decode().splitlines()
        )
        if not robots.can_fetch("StageRadar", base + "/jobs"):
            raise SourceError("Recherche Workday exclue par robots.txt.")
        facets = {} if self.board == "deloitte" else {"locationCountry": [FRANCE]}
        candidates = {}
        fetched_paths = set()
        skipped = 0
        complete = True
        for term in ("stage", "intern"):
            count = 0
            term_paths = set()
            expected_total = None
            for page in page_numbers():
                await asyncio.sleep(0.25)
                data = await fetch_json(
                    client,
                    base + "/jobs",
                    "Workday",
                    method="POST",
                    body={
                        "appliedFacets": facets,
                        "limit": PAGE_SIZE,
                        "offset": page * PAGE_SIZE,
                        "searchText": term,
                    },
                )
                rows, total = data.get("jobPostings"), data.get("total")
                if not isinstance(rows, list) or type(total) is not int or total < 0:
                    raise SourceError("Recherche Workday sans pagination valide.")
                # CXS reports total=0 on subsequent pages even when jobs remain.
                if expected_total is None:
                    expected_total = total
                elif total not in {0, expected_total}:
                    complete = False
                count += len(rows)
                for row in rows:
                    try:
                        path, title = row["externalPath"], row["title"]
                        if not isinstance(path, str) or not re.fullmatch(
                            r"/job/(?:[^/?#]+/)*[^/?#]+", path
                        ):
                            raise ValueError
                        decoded = unquote(path)
                        if (
                            any(part in {".", ".."} for part in decoded.split("/"))
                            or "\\" in decoded
                        ):
                            raise ValueError
                        fetched_paths.add(path)
                        if path in term_paths:
                            raise ValueError
                        term_paths.add(path)
                        if matched(normalize(title), INTERNSHIP):
                            candidates[path] = row
                    except (AttributeError, KeyError, TypeError, ValueError):
                        skipped += 1
                if count >= expected_total:
                    complete = complete and count == expected_total
                    break
                if len(rows) != PAGE_SIZE:
                    complete = False
                    break
            else:
                complete = False
        known = {
            str(item.original_url).removeprefix(f"{origin}/{site}"): item
            for item in previous.values()
        }
        self.checked.intersection_update(candidates)
        self.ignored.intersection_update(candidates)
        ordered = sorted(
            candidates.keys() - self.ignored,
            key=lambda path: (
                matched(normalize(candidates[path]["title"]), TECH),
                matched(normalize(candidates[path].get("locationsText") or ""), IDF),
            ),
            reverse=True,
        )
        new = [path for path in ordered if path not in known]
        refresh = [path for path in ordered if path in known and path not in self.checked]
        if not refresh:
            self.checked.difference_update(known)
            refresh = [path for path in ordered if path in known]
        queue = new + refresh
        listings = {path: known[path] for path in candidates if path in known}
        checked = set()
        for path in queue:
            public_url = f"{origin}/{site}{path}"
            if not robots.can_fetch("StageRadar", public_url) or not robots.can_fetch(
                "StageRadar", base + path
            ):
                skipped += 1
                continue
            await asyncio.sleep(0.25)
            try:
                payload = await fetch_json(client, base + path, "Workday")
                listing = self.parse_job(payload, public_url)
                if listing:
                    listings[path] = listing
                else:
                    self.ignored.add(path)
                checked.add(path)
            except SourceError as exc:
                if exc.retry_after:
                    raise
                skipped += 1
            except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
                skipped += 1
        self.checked.update(checked)
        return Batch(
            list(listings.values()),
            skipped,
            complete=complete and not skipped,
            fetched=len(fetched_paths),
            authoritative=False,
        )

    def parse_job(self, payload: dict, public_url: str) -> ListingInput | None:
        info = payload["jobPostingInfo"]
        country = info.get("country") or {}
        if (
            country.get("id") != FRANCE
            and str(country.get("descriptor", "")).casefold() != "france"
        ):
            return None
        if info.get("posted") is False or info.get("canApply") is False:
            return None
        # In the verified CXS responses startDate matches JobPosting.datePosted on the public page.
        # It is the publication date, and must never populate the internship's start_date.
        published = info.get("startDate")
        remote = info.get("remoteType")
        location = info.get("location") or ""
        if not re.search(r"\bfrance\b", location, re.IGNORECASE):
            location = ", ".join(filter(None, [location, "France"]))
        return ListingInput(
            external_id=info["jobReqId"],
            employer=self.label,
            title=info["title"],
            description=info.get("jobDescription") or "",
            original_url=public_url,
            apply_url=public_url,
            location=location,
            published_at=datetime.fromisoformat(published) if published else None,
            remote={"Remote": "télétravail", "Hybrid": "hybride", "On-Site": "sur site"}.get(
                remote
            ),
        )
