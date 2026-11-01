import asyncio
import re

import httpx


async def post_with_retry(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    for attempt in range(4):
        try:
            response = await client.post(url, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError):
            if attempt == 3:
                raise
            await asyncio.sleep(2**attempt)
            continue
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            retry_after = response.headers.get("retry-after", "")
            if not retry_after:
                try:
                    retry_after = str(response.json().get("retryAfter", ""))
                except ValueError:
                    retry_after = ""
            seconds = re.fullmatch(r"(\d+(?:\.\d+)?)s?", retry_after)
            delay = min(float(seconds[1]), 60) if seconds else 2**attempt
            await asyncio.sleep(delay)
            continue
        # Never include response bodies or authenticated request headers in logs.
        if response.is_error:
            raise RuntimeError(f"Upstream {httpx.URL(url).host} returned HTTP {response.status_code}")
        return response
    raise RuntimeError("Retry budget exhausted")
