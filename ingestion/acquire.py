"""Bounded opt-in Sefaria metadata acquisition (stdlib, no text downloads)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time
from urllib import error, parse, request

from ingestion.sefaria_links import approved_source_url, file_sha256

GCS_BASE = "https://storage.googleapis.com/sefaria-export/links/"
API_BASE = "https://www.sefaria.org/api/links/"
SHARD_RE = re.compile(r"^links(?:0|[1-9][0-9]?)\.csv$")
USER_AGENT = "DvirOS-Research-Metadata/0.3.0 (public Sefaria API, bounded requests)"


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("HTTP redirect refused for allowlisted Sefaria source.")


def opener():
    return request.build_opener(request.ProxyHandler({}), NoRedirect())


def api_url(index_ref: str) -> str:
    if not isinstance(index_ref, str) or not index_ref.strip() or len(index_ref) > 220:
        raise ValueError("Invalid curated API title.")
    if any(ord(ch) < 32 for ch in index_ref):
        raise ValueError("Invalid API title.")
    url = API_BASE + parse.quote(index_ref.strip(), safe="") + "?with_text=0"
    return approved_source_url(url)


def fetch_api_links(index_ref: str, *, client=None, max_bytes: int = 8_000_000,
                    retries: int = 2, sleep=time.sleep) -> tuple[str, list]:
    """Fetch no text; retry transient errors; never follow redirects."""
    url = api_url(index_ref)
    client = client or opener()
    if not 0 < max_bytes <= 16_000_000:
        raise ValueError("API response byte limit must be 1..16MB.")
    for attempt in range(retries + 1):
        req = request.Request(url, headers={
            "Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": USER_AGENT,
        })
        try:
            with client.open(req, timeout=20) as response:
                if response.status != 200:
                    raise RuntimeError(f"Unexpected Sefaria API status {response.status}.")
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise ValueError("Sefaria metadata API exceeded byte limit.")
                value = json.loads(raw.decode("utf-8"))
                if not isinstance(value, list):
                    raise ValueError("Sefaria links API did not return a list.")
                return url, value
        except error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries:
                raise RuntimeError(f"Sefaria API HTTP {exc.code}; no data staged.") from None
        except (TimeoutError, error.URLError) as exc:
            if attempt == retries:
                raise RuntimeError("Sefaria API unavailable; no data staged.") from exc
        if attempt < retries:
            sleep(min(2 ** attempt, 4))
    raise RuntimeError("API retry limit reached.")


def parse_content_range(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", value)
    if not match:
        raise ValueError("Invalid Content-Range header.")
    start, end, total = map(int, match.groups())
    if not (0 <= start <= end < total):
        raise ValueError("Contradictory Content-Range header.")
    return start, end, total


def fetch_gcs_shard(name: str, destination: Path, *, max_bytes: int = 300_000_000,
                    client=None, chunk_size: int = 1024 * 1024) -> dict:
    """Download a single named metadata CSV with ETag-based resume.

    A partial response is only appended if Content-Range starts at the
    saved part byte offset AND matches the saved source validator.
    Otherwise the download is rejected; no stale bytes are combined.
    """
    if not SHARD_RE.fullmatch(name):
        raise ValueError("Only linksN.csv from the GCS links directory is allowed.")
    if not 0 < max_bytes <= 400_000_000 or chunk_size <= 0:
        raise ValueError("Invalid download budget.")
    url = approved_source_url(GCS_BASE + name)
    destination = Path(destination)
    if destination.exists() and destination.is_symlink():
        raise ValueError("Refusing destination symlink.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    checkpoint = destination.with_name(destination.name + ".resume.json")
    for path in (partial, checkpoint):
        if path.is_symlink():
            raise ValueError("Refusing partial/checkpoint symlink.")
    receipt = destination.with_name(destination.name + ".receipt.json")
    if destination.exists():
        if receipt.is_symlink() or not receipt.is_file():
            raise ValueError("Existing CSV lacks trusted fetch receipt; refuse reuse.")
        info = json.loads(receipt.read_text(encoding="utf-8"))
        digest = file_sha256(destination)
        if (info.get("url") != url or info.get("sha256") != digest
                or info.get("bytes") != destination.stat().st_size
                or info["bytes"] > max_bytes):
            raise ValueError("Existing source differs from its receipt or byte budget.")
        return {"url": url, "sha256": digest,
                "bytes": destination.stat().st_size, "reused": True}
    offset = 0
    validator = None
    if partial.exists() or checkpoint.exists():
        if not partial.is_file() or not checkpoint.is_file():
            raise ValueError("Incomplete resume state; refuse unsafe append.")
        meta = json.loads(checkpoint.read_text(encoding="utf-8"))
        validator = meta.get("etag")
        if meta.get("url") != url or not isinstance(validator, str) or not validator:
            raise ValueError("Missing matching ETag for safe resume.")
        offset = partial.stat().st_size
        if offset <= 0 or offset >= max_bytes:
            raise ValueError("Invalid resume offset.")
    headers = {"Accept-Encoding": "identity", "User-Agent": USER_AGENT}
    if offset:
        headers["Range"] = f"bytes={offset}-"
        headers["If-Range"] = validator
    client = client or opener()
    req = request.Request(url, headers=headers)
    with client.open(req, timeout=45) as response:
        status = response.status
        new_etag = response.headers.get("ETag")
        if not new_etag:
            raise ValueError("GCS response needs an ETag for resumable metadata retrieval.")
        if response.headers.get("Content-Encoding", "identity") != "identity":
            raise ValueError("Compressed range response is not safe to append.")
        if offset and status != 206:
            raise ValueError("Range resume refused: resource changed or server ignored Range.")
        if not offset and status != 200:
            raise ValueError(f"Expected HTTP 200 on first request, got {status}.")
        total = None
        if status == 206:
            start, end, total = parse_content_range(response.headers.get("Content-Range", ""))
            if start != offset or new_etag != validator:
                raise ValueError("Range/ETag mismatch: refusing mixed-version file.")
        else:
            length = response.headers.get("Content-Length")
            total = int(length) if length and length.isdigit() else None
        if total is not None and total > max_bytes:
            raise ValueError("GCS metadata shard exceeds configured byte budget.")
        if not offset:
            checkpoint.write_text(json.dumps({"url": url, "etag": new_etag}) + "\n", encoding="utf-8")
        written = offset
        with partial.open("ab" if offset else "wb") as out:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("Download exceeded byte limit; partial retained for inspection.")
                out.write(chunk)
        if total is not None and written != total:
            raise RuntimeError("Incomplete shard download retained for safe resume.")
    digest = file_sha256(partial)
    metadata = {"url": url, "sha256": digest, "bytes": partial.stat().st_size,
                "etag": new_etag}
    receipt.write_text(json.dumps(metadata, sort_keys=True) + "\\n", encoding="utf-8")
    partial.replace(destination)
    checkpoint.unlink(missing_ok=True)
    return {"url": url, "sha256": digest,
            "bytes": destination.stat().st_size, "reused": False}
