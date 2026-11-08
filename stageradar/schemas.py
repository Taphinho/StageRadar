from datetime import UTC, date, datetime
from enum import StrEnum
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

PARIS = ZoneInfo("Europe/Paris")

MANUAL_SOURCES = {
    "linkedin": "LinkedIn Jobs",
    "indeed": "Indeed",
    "hellowork": "HelloWork",
    "wttj": "Welcome to the Jungle",
    "jobteaser": "JobTeaser",
    "apec": "Apec",
    "france-travail": "France Travail",
    "workday": "Workday",
    "successfactors": "SAP SuccessFactors",
    "orange-jobs": "Orange Jobs (France)",
    "career": "Site carrière",
    "email": "Alerte e-mail",
    "rss": "Flux RSS",
    "other": "Autre",
}


def utc_now() -> datetime:
    # SQLite stores naive timestamps. Every persisted timestamp is UTC.
    return datetime.now(UTC).replace(tzinfo=None)


def paris_date(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(PARIS).date()


def canonical_url(value: str) -> str:
    parts = urlsplit(value)
    tracking = {"gh_src", "gclid", "fbclid", "mc_cid", "mc_eid"}
    query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in tracking
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path.rstrip("/") or "/", urlencode(sorted(query)), "")
    )


class Status(StrEnum):
    REVIEW = "review"
    TODO = "todo"
    SENT = "sent"
    FOLLOW_UP = "follow_up"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"
    ARCHIVED = "archived"


class ListingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str | None = Field(default=None, min_length=1, max_length=200)
    employer: str = Field(min_length=1, max_length=250)
    title: str = Field(min_length=1, max_length=350)
    description: str = Field(default="", max_length=200_000)
    location: str | None = Field(default=None, max_length=500)
    contract: str | None = Field(default=None, max_length=100)
    duration_months: int | None = Field(default=None, ge=1, le=36)
    start_date: date | None = None
    remote: str | None = Field(default=None, max_length=100)
    skills: list[str] = Field(default_factory=list, max_length=100)
    original_url: HttpUrl
    apply_url: HttpUrl | None = None
    published_at: datetime | None = None

    @field_validator(
        "external_id", "employer", "title", "location", "contract", "remote", mode="before"
    )
    @classmethod
    def trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("original_url", "apply_url")
    @classmethod
    def disallow_url_credentials(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and (value.username is not None or value.password is not None):
            raise ValueError("Les identifiants dans les URL sont interdits.")
        return value

    @field_validator("published_at")
    @classmethod
    def to_utc(cls, value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    @field_validator("skills")
    @classmethod
    def validate_skills(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 100 for item in value):
            raise ValueError("Chaque compétence doit contenir de 1 à 100 caractères.")
        return list(dict.fromkeys(item.strip() for item in value))


class ManualInput(ListingInput):
    platform: str

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, value: str) -> str:
        if value not in MANUAL_SOURCES:
            raise ValueError("Plateforme inconnue.")
        return value


class ApplicationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status | None = None
    favorite: bool | None = None
    hidden: bool | None = None
    notes: str | None = Field(default=None, max_length=20_000)
    applied_on: date | None = None
    reminder_on: date | None = None

    @field_validator("status", "favorite", "hidden", "notes")
    @classmethod
    def non_nullable(cls, value: object) -> object:
        if value is None:
            raise ValueError("Ce champ ne peut pas être nul.")
        return value


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=60_000)


class ResumeFileInput(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=6_700_000)
