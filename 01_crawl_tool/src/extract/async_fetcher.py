"""Async parallel detail fetcher for 52wmb Pro 2026.

Issues concurrent GET requests to /api/raw/trade/detail/{bill_id} using
access-token + auth-pd-user headers extracted from the Selenium session.

`bill_specs` is an iterable of `(bill_id, trade_date)` tuples. The trade_date
is mandatory (the server requires it in the query string — the UI reads it
from the row that was clicked).
"""
import asyncio
import time

import httpx

try:
    from ..observability import SessionExpired, ApiError
    from . import http_fetcher as _hc
except ImportError:  # pragma: no cover
    import sys, os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from observability import SessionExpired, ApiError
    from extract import http_fetcher as _hc


class TokenBucket:
    def __init__(self, rps):
        self._interval = 1.0 / max(rps, 1)
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            wait = self._next - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next = max(now, self._next) + self._interval


async def _fetch_one(client, bill_id, trade_date, country, ie, bucket, sem, attempts):
    async with sem:
        last_error = None
        params = {
            "country": country, "ie": ie,
            "trade_date": trade_date, "lang": "en",
        }
        path = _hc.DETAIL_PATH_TEMPLATE.format(bill_id=bill_id)
        for i in range(attempts):
            await bucket.acquire()
            try:
                r = await client.get(path, params=params)
            except httpx.ProxyError as e:
                # Proxy auth failed (e.g. expired BrightData creds). Don't
                # bother retrying — every attempt will hit the same 407.
                # Return a distinctive ("proxy", ...) tag so callers can
                # detect the proxy failure and disable proxy for the rest
                # of the session.
                return bill_id, None, ("proxy", str(e))
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
                last_error = ("network", str(e))
                await asyncio.sleep(0.5 * (2 ** i))
                continue

            if r.status_code == 429:
                last_error = ("429", "rate limited")
                await asyncio.sleep(2 ** i)
                continue
            if r.status_code >= 500:
                last_error = (r.status_code, "server error")
                await asyncio.sleep(0.5 * (2 ** i))
                continue
            if r.status_code != 200:
                return bill_id, None, ("http", f"status={r.status_code}")

            try:
                body = r.json()
            except Exception as e:
                last_error = ("parse", str(e))
                continue

            state = body.get("state")
            if state == 0:
                return bill_id, body.get("data") or {}, None
            if state in (3001, 4003):
                raise SessionExpired(state, body.get("message", ""))
            last_error = (state, body.get("message", ""))

        return bill_id, None, last_error


async def fetch_many_async(access_token, pd_user, proxy, bill_specs, *,
                           user_agent=None, country="vietnam", ie=0,
                           concurrency=5, rps=20, attempts=3, timeout=15.0):
    """Yield `(bill_id, data_or_None, err_or_None)` tuples as they complete.

    `bill_specs`: iterable of `(bill_id, trade_date)` where trade_date is
    a string like '2026-02-28'.
    """
    bucket = TokenBucket(rps=rps)
    sem = asyncio.Semaphore(concurrency)
    headers = _hc.default_headers(
        access_token=access_token, pd_user=pd_user, user_agent=user_agent,
    )

    async with httpx.AsyncClient(
        base_url=_hc.BASE, proxy=proxy,
        timeout=httpx.Timeout(timeout, connect=5.0),
        headers=headers, follow_redirects=False,
    ) as client:
        tasks = [
            asyncio.create_task(_fetch_one(
                client, bid, tdate, country, ie, bucket, sem, attempts,
            ))
            for bid, tdate in bill_specs
        ]
        try:
            for coro in asyncio.as_completed(tasks):
                yield await coro
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()


def fetch_many(access_token, pd_user, proxy, bill_specs, **kwargs):
    """Blocking wrapper. Returns `(results_by_id: dict, errors_by_id: dict)`."""
    results = {}
    errors = {}

    async def _run():
        async for bill_id, data, err in fetch_many_async(
            access_token, pd_user, proxy, bill_specs, **kwargs,
        ):
            if data is not None:
                results[bill_id] = data
            else:
                errors[bill_id] = err

    asyncio.run(_run())
    return results, errors
