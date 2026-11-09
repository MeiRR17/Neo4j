"""Scholarly seed-corpus discovery from Sefaria *version metadata only*.

No text is downloaded, no version is silently approved and no index title
is assumed to exist before the API answers successfully.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time
from urllib import error, parse, request

from research_graph.ontology import edition_id, stable_id, work_id

SCHEMA_VERSION = "0.4.0"
DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "config" / "philosophy-seed-candidates.json"
VERSION_API_BASE = "https://www.sefaria.org/api/texts/versions/"
RIGHTS_LICENSES = frozenset({"Public Domain", "CC0", "CC-BY", "CC-BY-SA", "CC-BY-NC"})
THEMES = frozenset({"philosophy", "ethics", "thought", "mysticism"})
MAX_METADATA_BYTES = 2_000_000
INDEX_LIMIT = 20


def compact_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def checksum(value: object) -> str:
    return hashlib.sha256(compact_json(value)).hexdigest()


def safe_title(title: str) -> str:
    if not isinstance(title, str) or title != title.strip() or not (2 <= len(title) <= 120):
        raise ValueError("Title must be a nonempty exact index name (2..120 chars).")
    if any(ord(x) < 32 for x in title) or any(x in title for x in ("\\", "/", "?", "#", "%")):
        raise ValueError("Index title contains unsafe characters.")
    return title


def versions_url(title: str) -> str:
    return VERSION_API_BASE + parse.quote(safe_title(title), safe="")


def load_catalog(path: Path = DEFAULT_CATALOG) -> list[dict]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Catalog must be a regular non-symlink JSON file.")
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if catalog.get("schema_version") != SCHEMA_VERSION or catalog.get("status") != "CANDIDATES_NOT_VERIFIED":
        raise ValueError("Catalog provenance/status mismatch.")
    entries = catalog.get("works")
    if not isinstance(entries, list) or not 12 <= len(entries) <= INDEX_LIMIT:
        raise ValueError("Expected 12..20 candidate works.")
    result = []
    seen = set()
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Bad seed catalog item.")
        title = safe_title(item.get("index_title"))
        theme = item.get("theme")
        if theme not in THEMES or title in seen:
            raise ValueError("Unknown theme or duplicate candidate index title.")
        seen.add(title)
        result.append({"index_title": title, "theme": theme})
    return result


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Sefaria metadata endpoint redirected; refusing external destination.")


def request_versions(title: str, *, client=None, sleep=time.sleep) -> list:
    """Opt-in 2MB bounded HTTPS GET, two retries of transient responses."""
    url = versions_url(title)
    client = client or request.build_opener(request.ProxyHandler({}), NoRedirect())
    for attempt in range(3):
        req = request.Request(
            url,
            headers={
                "Accept": "application/json", "Accept-Encoding": "identity",
                "User-Agent": "DvirOS-Scholarly-Metadata/0.4.0",
            },
        )
        try:
            with client.open(req, timeout=20) as response:
                if response.status != 200:
                    raise ValueError(f"Unexpected version API status: {response.status}")
                if response.headers.get("Content-Encoding", "identity") != "identity":
                    raise ValueError("Compressed response rejected for deterministic size budget.")
                data = response.read(MAX_METADATA_BYTES + 1)
                if len(data) > MAX_METADATA_BYTES:
                    raise ValueError("Version metadata response exceeded the byte limit.")
                parsed = json.loads(data.decode("utf-8"))
                if not isinstance(parsed, list):
                    raise ValueError("Versions API response must be a JSON array.")
                return parsed
        except error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise ValueError(f"Version metadata unavailable (HTTP {exc.code}).") from None
        except (TimeoutError, error.URLError) as exc:
            if attempt == 2:
                raise ValueError("Sefaria metadata unavailable; no version invented.") from exc
        sleep(min(2 ** attempt, 4))
    raise RuntimeError("Retry boundary unexpectedly reached.")


def parse_versions(index_title: str, raw: object) -> tuple[list[dict], list[dict]]:
    """Create *pending* edition inventory; malformed rows are quarantined."""
    index_title = safe_title(index_title)
    if not isinstance(raw, list):
        raise ValueError("Version metadata must be a JSON array.")
    if len(raw) > 500:
        raise ValueError("Too many versions for one index.")
    valid: list[dict] = []
    rejected: list[dict] = []
    seen = set()
    wid = work_id("sefaria", index_title)
    for i, item in enumerate(raw):
        reason = None
        if not isinstance(item, dict):
            reason = "invalid_version_object"
        else:
            title = item.get("title")
            version_title = item.get("versionTitle")
            lang = item.get("language")
            if title != index_title:
                reason = "index_title_mismatch"
            elif not isinstance(version_title, str) or not version_title.strip() or len(version_title) > 300:
                reason = "missing_version_title"
            elif lang not in {"he", "en"}:
                reason = "unsupported_language_bucket"
            elif isinstance(item.get("license"), (dict, list)):
                reason = "invalid_license"
            elif item.get("versionSource") is not None and not isinstance(item.get("versionSource"), str):
                reason = "invalid_version_source"
            else:
                version_title = version_title.strip()
                eid = edition_id(wid, lang + "|" + version_title)
                if eid in seen:
                    reason = "duplicate_edition"
                else:
                    seen.add(eid)
                    license_raw = str(item.get("license") or "").strip()
                    source = str(item.get("versionSource") or "").strip()
                    valid.append({
                        "work_id": wid, "index_title": index_title, "edition_id": eid,
                        "version_title": version_title, "language": lang,
                        "license_raw": license_raw, "version_source": source[:1000],
                        "rights_status": "pending_human_review",
                        "allowed_text_redistribution": False,
                        "license_supported_for_review": license_raw in RIGHTS_LICENSES,
                        "metadata_source": versions_url(index_title),
                    })
        if reason:
            rejected.append({"index_title": index_title, "ordinal": i, "reason": reason})
    return valid, rejected


def build_inventory(catalog: list[dict], snapshots: dict[str, object]) -> dict:
    """Offline reproducible contract. Caller supplies captured API responses."""
    titles = {item["index_title"] for item in catalog}
    if not 12 <= len(titles) <= INDEX_LIMIT or set(snapshots) - titles:
        raise ValueError("Snapshot titles must be a subset of the 12..20 catalog candidates.")
    versions, rejects, unavailable, sources = [], [], [], []
    for entry in catalog:
        title = entry["index_title"]
        if title not in snapshots:
            unavailable.append({"index_title": title, "reason": "not_discovered"})
            continue
        raw = snapshots[title]
        items, errors = parse_versions(title, raw)
        versions.extend(items)
        rejects.extend(errors)
        sources.append({
            "index_title": title, "url": versions_url(title),
            "response_sha256": checksum(raw),
            "source_record_id": stable_id("source", "sefaria", versions_url(title), checksum(raw)),
        })
        if not items:
            unavailable.append({"index_title": title, "reason": "no_valid_versions"})
    versions.sort(key=lambda x: (x["index_title"], x["language"], x["version_title"]))
    sources.sort(key=lambda x: x["index_title"])
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_sha256": checksum(catalog),
        "catalog_count": len(catalog), "status": "PENDING_HUMAN_RIGHTS_REVIEW",
        "source_type": "sefaria_version_metadata_only",
        "no_text_downloaded": True, "verified_edition_count": 0,
        "rights_decisions_generated": False,
        "candidates": catalog, "source_snapshots": sources, "editions": versions,
        "quarantine": rejects, "unavailable": unavailable,
    }


def write_immutable_json(path: Path, document: dict) -> None:
    """Refuse to overwrite changed review material or symlinked paths."""
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Refusing symlinked inventory destination.")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise ValueError("Inventory exists with different content; choose a new path.")
        return
    with path.open("x", encoding="utf-8") as output:
        output.write(encoded)
