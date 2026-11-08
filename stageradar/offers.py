import hashlib
import json
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from html import unescape

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from stageradar.config import Settings
from stageradar.database import Listing, Notification, Offer, Revision
from stageradar.schemas import ListingInput, canonical_url, paris_date
from stageradar.scoring import evaluate, normalize


def plain_text(description: str) -> str:
    if "&lt;" in description and "<" not in description:
        description = unescape(description)
    soup = BeautifulSoup(description, "html.parser")
    for tag in soup(["script", "style", "template"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def employer_key(employer: str) -> str:
    return normalize(employer).removesuffix(" sas").removesuffix(" sa").removesuffix(" s a")


def matching_offer(
    db: Session,
    source: str,
    item: ListingInput,
    canonical: str,
    text: str,
) -> Offer | None:
    possible = db.scalars(
        select(Offer)
        .where(Offer.employer_key == employer_key(item.employer))
        .options(selectinload(Offer.listings))
    )
    matches = []
    for offer in possible:
        if any(listing.source == source for listing in offer.listings):
            continue
        if any(canonical == listing.canonical for listing in offer.listings):
            return offer
        # Different requisitions can have the same generic title or even a common template.
        if offer.expired or normalize(offer.title) != normalize(item.title):
            continue
        if not item.location or normalize(item.location) != normalize(
            offer.details["location"] or ""
        ):
            continue
        for listing in offer.listings:
            if listing.closed_at:
                continue
            previous = ListingInput.model_validate(listing.snapshot)
            if any(
                a and b and a != b
                for a, b in (
                    (item.start_date, previous.start_date),
                    (item.duration_months, previous.duration_months),
                    (normalize(item.contract or ""), normalize(previous.contract or "")),
                )
            ):
                continue
            if item.published_at and previous.published_at:
                if abs(item.published_at - previous.published_at) > timedelta(days=14):
                    continue
            previous_text = normalize(plain_text(previous.description))
            if min(len(text), len(previous_text)) < 350:
                continue
            # Work with tokens and bound comparison costs on unusually long descriptions.
            left, right = text.split()[:1200], previous_text.split()[:1200]
            if min(len(left), len(right)) / max(len(left), len(right)) < 0.95:
                continue
            if SequenceMatcher(None, left, right).ratio() >= 0.97:
                matches.append(offer)
                break
    return matches[0] if len(matches) == 1 else None


def refresh_offer(offer: Offer, settings: Settings, now: datetime) -> None:
    active = [listing for listing in offer.listings if listing.closed_at is None]
    offer.expired = not active
    ranked = sorted(
        active or offer.listings,
        key=lambda listing: (
            bool(listing.snapshot["description"]),
            not listing.source.startswith("manual:"),
            len(listing.snapshot["description"]),
            listing.last_seen,
            listing.id or 0,
        ),
        reverse=True,
    )
    preferred = ranked[0]
    sources = [
        (listing.source, ListingInput.model_validate(listing.snapshot)) for listing in ranked
    ]
    item = sources[0][1].model_copy()
    field_sources = {}
    for field in ("location", "contract", "duration_months", "start_date", "remote"):
        for source, snapshot in sources:
            value = getattr(snapshot, field)
            if value:
                setattr(item, field, value)
                field_sources[field] = source
                break
    item.skills = list(
        dict.fromkeys(skill for listing in ranked for skill in listing.snapshot["skills"])
    )
    offer.employer = item.employer
    offer.employer_key = employer_key(item.employer)
    offer.title = item.title
    description = plain_text(item.description)
    published = [
        listing.snapshot["published_at"]
        for listing in active or offer.listings
        if listing.snapshot["published_at"]
    ]
    item.published_at = min(map(datetime.fromisoformat, published), default=None)
    offer.published_at = item.published_at
    offer.last_seen = max(listing.last_seen for listing in offer.listings)
    local_date = paris_date(now)
    offer.details, offer.score, offer.reasons, offer.domains = evaluate(
        item, description, settings, local_date
    )
    offer.details.update(
        description=description,
        original_url=str(item.original_url),
        apply_url=str(item.apply_url or item.original_url),
        primary_source=preferred.source,
        field_sources=field_sources,
    )
    offer.search_text = normalize(
        f"{item.title} {item.employer} {item.location or ''} {description} "
        + " ".join(offer.details["skills"])
    )


def ingest(
    db: Session,
    source: str,
    item: ListingInput,
    settings: Settings,
    now: datetime,
) -> tuple[Listing, bool, bool]:
    canonical = canonical_url(str(item.original_url))
    key = f"id:{item.external_id}" if item.external_id else f"url:{canonical}"
    listing = db.scalar(select(Listing).where(Listing.source == source, Listing.source_key == key))
    snapshot = item.model_dump(mode="json")
    description = plain_text(item.description)
    text = normalize(description)
    material = snapshot | {
        "description": " ".join(description.split()),
        "original_url": canonical,
        "apply_url": canonical_url(str(item.apply_url)) if item.apply_url else None,
    }
    fingerprint = hashlib.sha256(
        json.dumps(material, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    created = False
    if listing is None:
        offer = matching_offer(db, source, item, canonical, text)
        created = offer is None
        if offer is None:
            offer = Offer(first_seen=now, listings=[])
            db.add(offer)
        listing = Listing(
            source=source,
            source_key=key,
            first_seen=now,
            misses=0,
            snapshot=snapshot,
            fingerprint=fingerprint,
            canonical=canonical,
            last_seen=now,
        )
        offer.listings.append(listing)
        changed = not created
    else:
        offer = listing.offer
        changed = fingerprint != listing.fingerprint or listing.closed_at is not None
        if fingerprint != listing.fingerprint:
            db.add(Revision(listing_id=listing.id, snapshot=listing.snapshot, recorded_at=now))
        listing.snapshot = snapshot
        listing.fingerprint = fingerprint
        listing.canonical = canonical
        listing.last_seen = now
        listing.closed_at = None
        listing.misses = 0
    # Avoid an autoflush of the new Offer before the derived fields are populated.
    with db.no_autoflush:
        refresh_offer(offer, settings, now)
    db.flush()
    notification_key = f"offer:{offer.id}"
    if (
        settings.telegram_enabled
        and offer.score >= settings.alert_threshold
        and offer.details["internship"]
        and not offer.hidden
        and db.get(Notification, notification_key) is None
    ):
        db.add(Notification(key=notification_key, offer_id=offer.id, next_attempt=now))
    return listing, created, changed
