import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from stageradar.collectors.base import Batch, SourceError
from stageradar.collectors.http import fetch_bytes
from stageradar.schemas import ListingInput, utc_now
from stageradar.scoring import INTERNSHIP, matched, normalize

ORIGIN = "https://careers.thalesgroup.com"
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
SITEMAP_LIMIT = 16
DETAIL_LIMIT = 20
REFRESH_LIMIT = 5
CYBER = "cyber|cybersecurite|cybersecurity|pentest|soc|iam|devsecops|securite"
TECH = "informatique|software|cloud|reseaux|data|logiciel|devops"


def sitemap_paths(data: bytes, root: str, child: str, path_pattern: str) -> list[str]:
    try:
        if b"<!DOCTYPE" in data or b"\x00" in data:
            raise ValueError
        tree = ElementTree.fromstring(data)
        if tree.tag != SITEMAP_NS + root:
            raise ValueError
    except (ElementTree.ParseError, ValueError):
        raise SourceError("Sitemap Thales non valide.") from None
    paths = []
    for row in tree.findall(SITEMAP_NS + child):
        url = urlsplit(row.findtext(SITEMAP_NS + "loc") or "")
        if (
            url.scheme == "https"
            and url.netloc == "careers.thalesgroup.com"
            and not url.query
            and not url.fragment
            and re.fullmatch(path_pattern, url.path)
        ):
            paths.append(url.path)
    return paths


@dataclass(slots=True)
class Thales:
    label = "Thales"
    key = "thales:fr"
    ignored: set[str] = field(default_factory=set, init=False)
    checked: set[str] = field(default_factory=set, init=False)

    async def fetch(self, client: httpx.AsyncClient, previous: dict[str, ListingInput]) -> Batch:
        robots = RobotFileParser()
        robots_data = await fetch_bytes(client, f"{ORIGIN}/robots.txt", self.label)
        robot_lines = robots_data.decode("utf-8").splitlines()
        robots.parse(robot_lines)
        # Python 3.13's robotparser handles prefixes. Also honor wildcard disallow rules.
        wildcard_denials = []
        for line in robot_lines:
            directive, _, value = line.split("#", 1)[0].partition(":")
            rule = value.strip()
            if directive.strip().lower() == "disallow" and ("*" in rule or rule.endswith("$")):
                pattern = re.escape(rule.removesuffix("$")).replace(r"\*", ".*")
                wildcard_denials.append(re.compile(pattern + ("$" if rule.endswith("$") else "")))

        async def get(path: str) -> bytes:
            if not robots.can_fetch("StageRadar", ORIGIN + path) or any(
                rule.match(unquote(path)) for rule in wildcard_denials
            ):
                raise SourceError("Chemin Thales exclu par robots.txt.")
            await asyncio.sleep(max(1, robots.crawl_delay("StageRadar") or 0))
            return await fetch_bytes(client, ORIGIN + path, self.label)

        index = await get("/fr/fr/sitemap_index.xml")
        sitemaps = list(
            dict.fromkeys(
                sitemap_paths(index, "sitemapindex", "sitemap", r"/fr/fr/sitemap\d+\.xml")
            )
        )
        if not sitemaps or len(sitemaps) > SITEMAP_LIMIT:
            raise SourceError("Index des sitemaps Thales hors limites.")

        candidates = {}
        for path in sitemaps:
            for job in sitemap_paths(
                await get(path), "urlset", "url", r"/fr/fr/job/R\d{4,15}/[^/]+/?"
            ):
                job_id, slug = job.rstrip("/").rsplit("/", 2)[-2:]
                title = normalize(unquote(slug))
                if matched(title, INTERNSHIP):
                    candidates[job_id] = (job, matched(title, CYBER), matched(title, TECH))
        cutoff = utc_now() - timedelta(days=15)
        recent_previous = {
            key: item for key, item in previous.items() if recent_publication(item, cutoff)
        }
        self.ignored.update(previous.keys() - recent_previous.keys())
        previous = recent_previous
        self.ignored.intersection_update(candidates)
        self.checked.intersection_update(candidates)
        listings = {job_id: previous[job_id] for job_id in candidates if job_id in previous}
        queue = sorted(
            candidates.keys() - self.ignored,
            key=lambda job_id: (*candidates[job_id][1:], job_id),
            reverse=True,
        )
        new_jobs = [job_id for job_id in queue if job_id not in previous]
        refresh = [job_id for job_id in queue if job_id in previous and job_id not in self.checked]
        if not refresh:
            self.checked.difference_update(previous)
            refresh = [job_id for job_id in queue if job_id in previous]
        jobs = refresh[:REFRESH_LIMIT] if new_jobs else refresh[:DETAIL_LIMIT]
        new_batch = new_jobs[: DETAIL_LIMIT - len(jobs)]
        jobs += new_batch
        skipped = len(new_jobs) - len(new_batch)
        checked = set()
        for job_id in jobs:
            path = candidates[job_id][0]
            try:
                listing = self.parse_job(await get(f"/fr/fr/job/{job_id}"), job_id, path)
            except SourceError as exc:
                if exc.status_code in {404, 410}:
                    self.ignored.add(job_id)
                    continue
                raise
            except (AttributeError, KeyError, TypeError, ValueError):
                skipped += 1
                continue
            if listing and recent_publication(listing, cutoff):
                listings[job_id] = listing
                checked.add(job_id)
            else:
                self.ignored.add(job_id)
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
                country = str(address.get("addressCountry", "")).casefold()
                if country in {"fr", "fra", "france"}:
                    locations.append(
                        ", ".join(
                            filter(
                                None,
                                (
                                    address.get("addressLocality"),
                                    address.get("postalCode"),
                                    "France",
                                ),
                            )
                        )
                    )
            if not locations:
                return None
            workday = workday_posting(page, job_id)
            return ListingInput(
                external_id=job_id,
                employer=self.label,
                title=record["title"],
                description=record.get("description") or "",
                original_url=ORIGIN + path,
                apply_url=workday_job_url(workday.get("applyUrl"), job_id),
                location=" · ".join(dict.fromkeys(locations)),
                published_at=workday_posted_date(workday.get("postedDate"))
                or record.get("datePosted"),
            )
        raise ValueError("Fiche Thales sans JobPosting correspondant.")


def recent_publication(listing: ListingInput, cutoff: datetime) -> bool:
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=UTC)
    date = listing.published_at
    if date is None:
        return False
    if date.tzinfo is None:
        date = date.replace(tzinfo=UTC)
    return cutoff < date <= cutoff + timedelta(days=15)


def workday_posting(page: BeautifulSoup, job_id: str) -> dict:
    # The public page embeds the Workday posting separately from its JSON-LD metadata.
    for script in page.select("script"):
        text = script.string or ""
        assignment = re.search(r"\bphApp\.ddo\s*=\s*(?=\{)", text)
        if not assignment:
            continue
        try:
            payload, _ = json.JSONDecoder().raw_decode(text, assignment.end())
            job = payload["jobDetail"]["data"]["job"]
            if job["reqId"] == job_id and job.get("ats") == "WORKDAY":
                return job
        except (KeyError, TypeError, ValueError, RecursionError):
            continue
    return {}


def workday_posted_date(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return None


def workday_job_url(value: object, job_id: str) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    path = url.path.rstrip("/").removesuffix("/apply")
    if (
        url.scheme == "https"
        and url.netloc == "thales.wd3.myworkdayjobs.com"
        and re.fullmatch(rf"/(?:[a-z]{{2}}-[A-Z]{{2}}/)?Careers/job/.+_{job_id}(?:-\d+)?", path)
    ):
        return f"https://{url.netloc}{path}"
    return None
