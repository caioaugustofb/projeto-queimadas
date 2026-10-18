"""HTTP com retry e backoff exponencial.

- Repete em falha de rede, timeout, 408/425/429 e 5xx (respeitando Retry-After).
- NÃO repete em 4xx "de verdade" (404, 403...): levanta HttpError na hora.
- O jitter usa uma semente fixa (config.SEED), como exige o projeto.
"""
from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Callable

import requests

from src import config
from src.common.metadata import sha256_bytes  # noqa: F401  (reexport útil)

log = logging.getLogger(__name__)

RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_NETWORK_ERRORS = (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError)
_rng = random.Random(config.SEED)
_session: requests.Session | None = None


class HttpError(Exception):
    def __init__(self, url: str, message: str, status: int | None = None) -> None:
        super().__init__(f"{message} [{url}]")
        self.url, self.status = url, status


class _Retry(Exception):
    def __init__(self, reason: str, retry_after: float | None = None) -> None:
        super().__init__(reason)
        self.reason, self.retry_after = reason, retry_after


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = config.USER_AGENT
    return _session


def _retry_after(resp: requests.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    try:
        return min(float(value), 120.0) if value else None
    except ValueError:
        return None


def _single(method: str, url: str, *, stream: bool = False, **kwargs: Any) -> requests.Response:
    """Uma tentativa. Levanta _Retry (vale tentar de novo) ou HttpError (não vale)."""
    try:
        resp = _get_session().request(method, url, timeout=config.HTTP_TIMEOUT, stream=stream, **kwargs)
    except _NETWORK_ERRORS as exc:
        raise _Retry(f"{type(exc).__name__}: {exc}") from exc
    if resp.status_code in RETRY_STATUS:
        wait = _retry_after(resp)
        resp.close()
        raise _Retry(f"HTTP {resp.status_code}", wait)
    if resp.status_code >= 400:
        status = resp.status_code
        resp.close()
        raise HttpError(url, f"HTTP {status}", status)
    return resp


def _with_retries(url: str, attempt_fn: Callable[[], Any]) -> Any:
    last = "sem detalhe"
    for attempt in range(1, config.HTTP_MAX_ATTEMPTS + 1):
        wait_hint = None
        try:
            return attempt_fn()
        except _Retry as retry:
            last, wait_hint = retry.reason, retry.retry_after
        if attempt < config.HTTP_MAX_ATTEMPTS:
            delay = min(config.HTTP_BACKOFF_MAX, config.HTTP_BACKOFF_BASE * 2 ** (attempt - 1))
            delay *= 0.5 + _rng.random() / 2
            if wait_hint:
                delay = max(delay, wait_hint)
            log.warning("Tentativa %d/%d falhou (%s). Nova tentativa em %.1fs: %s",
                        attempt, config.HTTP_MAX_ATTEMPTS, last, delay, url)
            time.sleep(delay)
    raise HttpError(url, f"falhou após {config.HTTP_MAX_ATTEMPTS} tentativas ({last})")


def get_bytes(url: str, **kwargs: Any) -> bytes:
    def attempt() -> bytes:
        resp = _single("GET", url, **kwargs)
        try:
            return resp.content
        except _NETWORK_ERRORS as exc:
            raise _Retry(f"{type(exc).__name__}: {exc}") from exc
        finally:
            resp.close()
    return _with_retries(url, attempt)


def head_info(url: str) -> dict[str, str | None]:
    """ETag / Last-Modified / Content-Length via HEAD. {} se o servidor não suporta HEAD."""
    try:
        resp = _with_retries(url, lambda: _single("HEAD", url, allow_redirects=True))
    except HttpError as exc:
        if exc.status in (405, 501):
            return {}
        raise
    headers = resp.headers
    resp.close()
    return {"etag": headers.get("ETag"), "last_modified": headers.get("Last-Modified"),
            "content_length": headers.get("Content-Length")}


def download_file(url: str, dest: Path | str) -> dict[str, Any]:
    """Baixa em streaming para `dest` (via .part + rename) e devolve sha256 e bytes."""
    import hashlib

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    def attempt() -> dict[str, Any]:
        resp = _single("GET", url, stream=True)
        digest, size = hashlib.sha256(), 0
        try:
            with open(part, "wb") as fh:
                for block in resp.iter_content(chunk_size=1 << 20):
                    fh.write(block)
                    digest.update(block)
                    size += len(block)
        except _NETWORK_ERRORS as exc:
            raise _Retry(f"{type(exc).__name__} no meio do download: {exc}") from exc
        finally:
            resp.close()
        expected = resp.headers.get("Content-Length")
        if expected and not resp.headers.get("Content-Encoding") and int(expected) != size:
            raise _Retry(f"download incompleto ({size} de {expected} bytes)")
        os.replace(part, dest)
        return {"sha256": digest.hexdigest(), "bytes": size}

    try:
        return _with_retries(url, attempt)
    finally:
        part.unlink(missing_ok=True)
