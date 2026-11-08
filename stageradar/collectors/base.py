from dataclasses import dataclass
from typing import Protocol

import httpx

from stageradar.schemas import ListingInput


@dataclass(slots=True)
class Batch:
    listings: list[ListingInput]
    skipped: int = 0
    complete: bool = False
    fetched: int | None = None
    authoritative: bool = True


class SourceError(Exception):
    def __init__(
        self, message: str, retry_after: int | None = None, *, status_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.status_code = status_code


class Collector(Protocol):
    key: str
    label: str

    async def fetch(
        self, client: httpx.AsyncClient, previous: dict[str, ListingInput]
    ) -> Batch: ...
