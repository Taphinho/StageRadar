import asyncio
import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from stageradar.collectors.base import SourceError

MAX_BODY = 12 * 1024 * 1024


def retry_seconds(value: str | None) -> int:
    if value:
        if value.isdigit() and len(value) <= 9:
            return max(1, int(value))
        try:
            delay = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
            return max(1, int(delay))
        except (TypeError, ValueError, OverflowError):
            pass
    return 1800


async def fetch_bytes(
    client: httpx.AsyncClient,
    url: str,
    provider: str,
    params: dict | None = None,
    *,
    max_body: int = MAX_BODY,
    total_timeout: int = 30,
    method: str = "GET",
    body: dict | None = None,
    form: dict | None = None,
    headers: dict[str, str] | None = None,
) -> bytes:
    for attempt in range(3):
        try:
            async with (
                asyncio.timeout(total_timeout),
                client.stream(
                    method, url, params=params, json=body, data=form, headers=headers
                ) as res,
            ):
                if res.status_code == 429 or (res.is_error and res.headers.get("Retry-After")):
                    raise SourceError(
                        f"{provider} demande de patienter (HTTP {res.status_code}).",
                        retry_seconds(res.headers.get("Retry-After")),
                    )
                res.raise_for_status()
                data = bytearray()
                async for chunk in res.aiter_bytes(chunk_size=65536):
                    data.extend(chunk)
                    if len(data) > max_body:
                        raise SourceError(f"Réponse {provider} trop volumineuse.")
            return bytes(data)
        except (TimeoutError, httpx.RequestError):
            if attempt == 2:
                raise SourceError(f"Connexion à {provider} impossible.") from None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 or attempt == 2:
                raise SourceError(
                    f"{provider} : HTTP {exc.response.status_code}.",
                    status_code=exc.response.status_code,
                ) from None
        await asyncio.sleep(2**attempt)
    raise AssertionError("Retry loop exhausted")


async def _fetch_json[T](
    client: httpx.AsyncClient,
    url: str,
    provider: str,
    expected: type[T],
    params: dict | None,
    *,
    method: str = "GET",
    body: dict | None = None,
) -> T:
    data = await fetch_bytes(client, url, provider, params, method=method, body=body)
    try:
        payload = json.loads(data)
    except (ValueError, RecursionError):
        raise SourceError(f"Réponse {provider} non valide.") from None
    if not isinstance(payload, expected):
        raise SourceError(f"Format JSON {provider} inattendu.")
    return payload


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    provider: str,
    params: dict | None = None,
    *,
    method: str = "GET",
    body: dict | None = None,
) -> dict:
    return await _fetch_json(client, url, provider, dict, params, method=method, body=body)


async def fetch_json_array(
    client: httpx.AsyncClient,
    url: str,
    provider: str,
    params: dict | None = None,
) -> list:
    return await _fetch_json(client, url, provider, list, params)
