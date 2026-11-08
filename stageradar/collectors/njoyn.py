import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from bs4 import BeautifulSoup

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_bytes
from stageradar.schemas import ListingInput
from stageradar.scoring import matched, normalize

ORIGIN = "https://cgi.njoyn.com"
PATH = "/corp/xweb/xweb.asp"
TECH = "cyber|security|securite|iam|cloud|devops|data|developpement|informatique"


@dataclass(slots=True)
class CGI:
    key = "career:cgi"
    label = "CGI"
    min_interval_minutes = 120
    checked: set[str] = field(default_factory=set, init=False)

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        candidates = {}
        complete = False
        for page in range(1, 11):
            data = await fetch_bytes(
                client,
                ORIGIN + PATH,
                self.label,
                {"NTKN": "c", "clid": "21001", "Page": "joblisting", "lang": "2"},
                method="POST",
                form={
                    "Inp_country": "FR",
                    "Inp_Jobtype": "INT",
                    "pn": str(page),
                    "s": " EnterDate Desc ",
                },
            )
            html = BeautifulSoup(data, "html.parser")
            found = 0
            for anchor in html.select("a[href]"):
                query = {
                    k.lower(): v[0] for k, v in parse_qs(urlsplit(anchor["href"]).query).items()
                }
                identifier = query.get("jobid", "")
                if query.get("page", "").lower() != "jobdetails" or not re.fullmatch(
                    r"J\d{4}-\d+", identifier
                ):
                    continue
                if identifier in candidates:
                    continue
                context = anchor.find_parent("tr") or anchor.parent.parent.parent
                text = context.get_text(" ", strip=True)
                candidates[identifier] = (matched(normalize(text), TECH), text)
                found += 1
            text = html.get_text(" ", strip=True)
            pagination = re.search(r"Page\s+(\d+)\s+de\s+(\d+)", text)
            if pagination and int(pagination[1]) == int(pagination[2]):
                complete = True
                break
            if not found:
                if not candidates:
                    raise SourceError("CGI : recherche publique non reconnue.")
                break
        known = dict(previous)
        ordered = sorted(candidates, key=lambda key: candidates[key], reverse=True)
        fresh = [key for key in ordered if key not in previous]
        refresh = [key for key in ordered if key in previous and key not in self.checked]
        if not refresh:
            self.checked.clear()
            refresh = [key for key in ordered if key in previous]
        queue = fresh + refresh
        skipped = 0
        for identifier in queue:
            params = {
                "NTKN": "c",
                "clid": "21001",
                "Page": "JobDetails",
                "Jobid": identifier,
                "lang": "2",
            }
            url = ORIGIN + PATH + "?" + urlencode(params)
            try:
                raw = await fetch_bytes(client, ORIGIN + PATH, self.label, params)
                known[identifier] = self.parse_job(raw, identifier, url)
                self.checked.add(identifier)
            except SourceError as exc:
                if exc.retry_after:
                    raise
                skipped += 1
            except (ValueError, TypeError, KeyError, AttributeError):
                skipped += 1
            await asyncio.sleep(0.25)
        return Batch(
            list(known.values()),
            skipped,
            complete=complete and not skipped,
            fetched=len(candidates),
            authoritative=False,
        )

    def parse_job(self, data: bytes, identifier: str, url: str) -> ListingInput:
        html = BeautifulSoup(data, "html.parser")
        for script in html.select('script[type="application/ld+json"]'):
            try:
                record = json.loads(script.string or "")
            except (ValueError, RecursionError):
                continue
            if not isinstance(record, dict) or record.get("@type") != "JobPosting":
                continue
            address = record["jobLocation"]["address"]
            if normalize(address.get("addressCountry", "").strip()) not in {"fr", "france"}:
                raise ValueError("Localisation CGI hors France.")
            description = html.select_one(".job-posting-content")
            return ListingInput(
                external_id=identifier,
                employer=self.label,
                title=record["title"],
                description=str(description) if description else record.get("description", ""),
                contract=record.get("employmentType"),
                location=", ".join(
                    filter(
                        None,
                        (address.get("addressLocality"), address.get("addressRegion"), "France"),
                    )
                ),
                original_url=url,
                published_at=datetime.fromisoformat(record["datePosted"])
                if record.get("datePosted")
                else None,
            )
        raise ValueError("Fiche CGI sans JobPosting.")
