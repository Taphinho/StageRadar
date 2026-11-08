import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import unquote, urlsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_bytes
from stageradar.schemas import ListingInput
from stageradar.scoring import INTERNSHIP, matched, normalize

ORIGIN = "https://orange.jobs"
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
SITEMAP_LIMIT = 8
TECH = "cyber|securite|security|vulnerabilites|pentest|soc|informatique|cloud|devops|reseaux|data"


def sitemap_paths(data: bytes, root_tag: str, row_tag: str, pattern: str) -> list[str]:
    try:
        if b"<!DOCTYPE" in data or b"\x00" in data:
            raise ValueError
        root = ElementTree.fromstring(data)
        if root.tag != SITEMAP_NS + root_tag:
            raise ValueError
    except (ElementTree.ParseError, ValueError):
        raise SourceError("Sitemap Orange Jobs non valide.") from None
    result = []
    for row in root.findall(SITEMAP_NS + row_tag):
        url = urlsplit(row.findtext(SITEMAP_NS + "loc") or "")
        if (
            url.scheme == "https"
            and url.netloc == "orange.jobs"
            and not url.query
            and not url.fragment
            and re.fullmatch(pattern, url.path)
        ):
            result.append(url.path)
    return list(dict.fromkeys(result))


def embedded_job(page: BeautifulSoup, job_id: str) -> dict:
    for script in page.select("script"):
        text = script.string or ""
        assignment = re.search(r"\bphApp\.ddo\s*=\s*(?=\{)", text)
        if not assignment:
            continue
        try:
            payload, _ = json.JSONDecoder().raw_decode(text, assignment.end())
            job = payload["jobDetail"]["data"]["job"]
            if job["jobId"] == job_id:
                return job
        except (KeyError, TypeError, ValueError, RecursionError):
            continue
    return {}


@dataclass(slots=True)
class OrangeJobs:
    key = "orangejobs:fr"
    label = "Orange Jobs France"
    min_interval_minutes = 120
    checked: set[str] = field(default_factory=set, init=False)
    ignored: set[str] = field(default_factory=set, init=False)

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        robots = RobotFileParser()
        robot_data = await fetch_bytes(client, f"{ORIGIN}/robots.txt", self.label)
        robots.parse(robot_data.decode("utf-8").splitlines())

        async def get(path: str) -> bytes:
            if not robots.can_fetch("StageRadar", ORIGIN + path):
                raise SourceError("Chemin Orange Jobs exclu par robots.txt.")
            await asyncio.sleep(max(0.25, robots.crawl_delay("StageRadar") or 0))
            return await fetch_bytes(client, ORIGIN + path, self.label)

        sitemaps = sitemap_paths(
            await get("/fr/fr/sitemap_index.xml"),
            "sitemapindex",
            "sitemap",
            r"/fr/fr/sitemap\d+\.xml",
        )
        if not sitemaps or len(sitemaps) > SITEMAP_LIMIT:
            raise SourceError("Index des sitemaps Orange Jobs hors limites.")
        candidates = {}
        for path in sitemaps:
            for job in sitemap_paths(
                await get(path), "urlset", "url", r"/fr/fr/job/[A-Za-z0-9-]{1,80}/[^/]+/?"
            ):
                job_id, slug = job.rstrip("/").rsplit("/", 2)[-2:]
                title = normalize(unquote(slug))
                if matched(title, INTERNSHIP):
                    candidates[job_id] = (job, matched(title, TECH))
        self.ignored.intersection_update(candidates)
        self.checked.intersection_update(candidates)
        ordered = sorted(candidates, key=lambda key: (candidates[key][1], key), reverse=True)
        fresh = [key for key in ordered if key not in previous and key not in self.ignored]
        refresh = [key for key in ordered if key in previous and key not in self.checked]
        if not refresh:
            self.checked.difference_update(previous)
            refresh = [key for key in ordered if key in previous]
        queue = fresh + refresh
        skipped = 0
        listings = dict(previous)
        checked = set()
        for job_id in queue:
            try:
                item = self.parse_job(
                    await get(f"/fr/fr/job/{job_id}"), job_id, candidates[job_id][0]
                )
                if item is None:
                    self.ignored.add(job_id)
                else:
                    listings[job_id] = item
                    checked.add(job_id)
            except SourceError as exc:
                if exc.status_code in {404, 410}:
                    self.ignored.add(job_id)
                    continue
                raise
            except (AttributeError, KeyError, TypeError, ValueError):
                skipped += 1
        self.checked.update(checked)
        return Batch(
            list(listings.values()),
            skipped,
            complete=not skipped,
            fetched=len(candidates),
            authoritative=False,
        )

    def parse_job(self, data: bytes, job_id: str, path: str) -> ListingInput | None:
        page = BeautifulSoup(data, "html.parser")
        job = embedded_job(page, job_id)
        for script in page.select('script[type="application/ld+json"]'):
            try:
                record = json.loads(script.string or "")
            except (ValueError, RecursionError):
                continue
            if not isinstance(record, dict) or record.get("@type") != "JobPosting":
                continue
            if (record.get("identifier") or {}).get("value") != job_id:
                continue
            places = record.get("jobLocation") or []
            locations = []
            for place in places if isinstance(places, list) else [places]:
                address = place.get("address") or {}
                country = address.get("addressCountry") or ""
                if isinstance(country, dict):
                    country = country.get("name", "")
                if normalize(str(country)) in {"fr", "france", "fra"}:
                    locations.append(address.get("addressLocality") or "France")
            if not locations:
                return None
            description = job.get("description") or record.get("description") or ""
            introduction = BeautifulSoup(description[:6000], "html.parser").get_text(
                " ", strip=True
            )
            publication = re.search(
                r"Date de publication\s*:\s*([A-Z][a-z]{2}\s+\d{1,2},\s*\d{4})",
                introduction,
            )
            # Orange's postedDate and JSON-LD can be refreshed by syndication. Use the
            # original date stated in the description, otherwise leave it unknown.
            published = datetime.strptime(publication[1], "%b %d, %Y") if publication else None
            company = job.get("company") or (record.get("hiringOrganization") or {}).get("name")
            employer = (
                "Orange Cyberdefense" if "cyberdefense" in normalize(company or "") else "Orange"
            )
            return ListingInput(
                external_id=job_id,
                employer=employer,
                title=record["title"],
                description=description,
                original_url=ORIGIN + path,
                location=" · ".join(dict.fromkeys(locations)) + ", France",
                contract=job.get("contractType"),
                published_at=published,
            )
        raise ValueError("Fiche Orange Jobs sans JobPosting correspondant.")
